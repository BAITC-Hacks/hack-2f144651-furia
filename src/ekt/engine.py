"""Pure local orchestration: validated canonical inputs → explanations + orders."""
from dataclasses import dataclass
import hashlib
import math
import numpy as np
import pandas as pd
from .schema import KEY, Bundle, normalize, validate, select, fingerprint
from .demand import build_demand
from .forecast import forecast


@dataclass
class Calculation:
    rows: pd.DataFrame
    details: dict
    fingerprint: str
    config: dict


def order_quantity(demand, safety, available, inbound, multiple, minimum=0):
    values = [demand, safety, available, inbound, multiple, minimum]
    if not all(np.isfinite(values)) or multiple <= 0 or minimum < 0 or min(demand, safety, inbound) < 0:
        raise ValueError("Неверные числовые параметры заказа")
    net = max(0., demand + safety - available - inbound)
    quantity = 0. if net <= 1e-10 else math.ceil(max(net, minimum) / multiple - 1e-10) * multiple
    return net, round(quantity, 8)


def policy_for(bundle, product):
    table = bundle["policies"]
    supplier = table.loc[table["supplier_id"].eq(product.supplier_id)]
    category = supplier.loc[supplier["category_id"].eq(product.category_id).fillna(False)] if pd.notna(product.category_id) else supplier.iloc[0:0]
    fallback = supplier.loc[supplier["category_id"].isna()]
    selected = category if not category.empty else fallback
    if selected.empty:
        raise ValueError("Нет политики поставщика/категории: задайте срок поставки, период пересмотра, страховой запас и кратность")
    policy = selected.iloc[0].copy()
    if pd.notna(getattr(product, "unconfirmed_moq", None)):
        raise ValueError("Не подтверждена семантика MOQ товара: minimum или multiple; уточните и обновите товар")
    for field in ["min_order_qty", "order_multiple"]:
        value = getattr(product, field, None)
        if value is not None and pd.notna(value):
            policy[field] = float(value)
    return policy


def scoped_optional(bundle, name, product):
    frame = bundle[name]
    frame = frame.loc[frame["supplier_id"].eq(product.supplier_id)]
    if "sku_1c" in frame:
        exact = frame.loc[frame["sku_1c"].eq(product.sku_1c).fillna(False)]
        if not exact.empty:
            return exact
        frame = frame.loc[frame["sku_1c"].isna()]
    category = frame.loc[frame["category_id"].eq(product.category_id).fillna(False)] if pd.notna(product.category_id) else frame.iloc[0:0]
    return category if not category.empty else frame.loc[frame["category_id"].isna()]


def calculate(bundle: Bundle, as_of, remove_oneoffs=True, compensate=True):
    bundle = normalize(bundle)
    errors = validate(bundle)
    if errors:
        raise ValueError("\n".join(errors))
    as_of = pd.Timestamp(as_of).normalize()
    config = {"as_of": as_of.date().isoformat(), "remove_oneoffs": remove_oneoffs, "compensate": compensate}
    digest = fingerprint(bundle, config)
    rows, details = [], {}
    for product in bundle["products"].itertuples():
        scopes = set()
        for name in ["sales", "monthly_sales", "stock_snapshots"]:
            frame = bundle[name]
            same = frame["supplier_id"].eq(product.supplier_id) & frame["sku_1c"].eq(product.sku_1c)
            scopes.update(frame.loc[same, "warehouse_scope"].dropna().tolist())
        for scope in sorted(scopes or ["UNSPECIFIED"]):
            key = (product.supplier_id, product.sku_1c, scope)
            row_id = hashlib.sha256("|".join(key).encode()).hexdigest()[:16]
            warnings, assumptions = [], []
            row = {"row_id": row_id, "supplier_id": product.supplier_id, "sku_1c": product.sku_1c,
                   "supplier_sku": product.supplier_sku, "name": product.name, "warehouse_scope": scope,
                   "unit": product.unit, "category_id": product.category_id, "as_of": as_of.date().isoformat(),
                   "data_mode": bundle.mode, "recommended_qty": np.nan, "urgency": "Нужны данные",
                   "calculation_id": digest[:16], "approval_status": "draft"}
            try:
                if scope == "UNSPECIFIED":
                    raise ValueError("Область склада не подтверждена: задайте warehouse_scope явно, не размножая общий остаток")
                if pd.isna(product.unit):
                    raise ValueError("Неизвестна базовая единица товара")
                if pd.isna(product.category_id):
                    warnings.append("Категория не предоставлена; применима только явная политика поставщика")
                policy = policy_for(bundle, product)
                horizon = int(policy.lead_time_days + policy.review_days)
                assumptions.append(f"Политика {policy.origin}: L={policy.lead_time_days:g}, R={policy.review_days:g}, safety={policy.safety_days:g}, MOQ={policy.min_order_qty:g}, кратность={policy.order_multiple:g}")
                sales = select(bundle["sales"], key)
                if not sales.empty and not sales["unit"].eq(product.unit).all():
                    raise ValueError("Единицы продаж и товара различаются: требуется явная конверсия до импорта")
                monthly = select(bundle["monthly_sales"], key)
                intervals = select(bundle["stockouts"], key)
                if sales["customer_id"].dropna().empty:
                    warnings.append("customer_id отсутствует: клиентские выбросы не проверены")
                if intervals.empty:
                    warnings.append("Подтверждённых stockout-интервалов нет: упущенный спрос не добавлен")
                demand = build_demand(sales, monthly, intervals, as_of, remove_oneoffs, compensate)
                prediction = forecast(demand, as_of, horizon, scoped_optional(bundle, "seasonal_prior", product), scoped_optional(bundle, "growth_plan", product))
                warnings += demand.warnings + prediction.warnings
                detail = {"demand": demand, "forecast": prediction, "policy": policy.to_dict()}
                details[row_id] = detail
                row.update(horizon_days=horizon, regular_demand=float(demand.daily.regular.sum()),
                           excluded_oneoff_qty=float(demand.daily.excluded.sum()), imputed_lost_demand=float(demand.daily.imputed.sum()),
                           expected_demand_horizon=float(prediction.daily.sum()), seasonal_source=prediction.seasonal_source,
                           trend_per_month=prediction.slope_per_month, training_end=prediction.training_end)
                stock = select(bundle["stock_snapshots"], key)
                stock = stock.loc[stock["as_of"].eq(as_of) & stock["snapshot_kind"].eq("current")]
                if stock.empty:
                    raise ValueError(f"Нет подтверждённого текущего остатка на {as_of:%Y-%m-%d}; исторический остаток не подставлен")
                snapshot = stock.iloc[0]
                if pd.notna(snapshot.available):
                    available = float(snapshot.available)
                elif pd.notna(snapshot.on_hand) and pd.notna(snapshot.reserved):
                    available = float(snapshot.on_hand - snapshot.reserved)
                else:
                    raise ValueError("Нужен доступный остаток либо on_hand и reserved; пустой резерв не равен нулю")
                if available < 0:
                    warnings.append("Отрицательный доступный остаток увеличивает потребность; проверьте учёт")
                inbound = select(bundle["inbound"], key)
                if "qty_source_unit" in inbound:
                    unconverted = inbound["qty_base_unit"].isna() & pd.to_numeric(inbound["qty_source_unit"], errors="coerce").ne(0) & ~inbound["status"].eq("cancelled")
                    if unconverted.any():
                        raise ValueError("Не подтверждены единицы пути: задайте количество в базовой единице для каждой партии")
                if inbound["status"].eq("pending").any():
                    warnings.append("Неподтверждённые партии pending не вычтены из потребности")
                active = inbound.loc[inbound["status"].eq("confirmed")]
                end = as_of + pd.Timedelta(days=horizon)
                on_time = active.loc[active["eta"].gt(as_of) & active["eta"].le(end)]
                late = active.loc[active["eta"].gt(end), "qty_base_unit"].sum()
                unknown = active.loc[active["eta"].isna(), "qty_base_unit"].sum()
                overdue = active.loc[active["eta"].le(as_of), "qty_base_unit"].sum()
                if unknown or overdue:
                    warnings.append(f"Не учтён путь без ETA ({unknown:g}) или просроченный ({overdue:g}); требуется подтверждение")
                if inbound.empty:
                    assumptions.append("Таблица пути для позиции пуста: подтверждённых открытых партий нет")
                expected = float(prediction.daily.sum())
                safety = float(prediction.daily.mean() * policy.safety_days)
                incoming = float(on_time["qty_base_unit"].sum())
                net, quantity = order_quantity(expected, safety, available, incoming, policy.order_multiple, policy.min_order_qty)
                arrivals = on_time.groupby("eta")["qty_base_unit"].sum().reindex(prediction.daily.index, fill_value=0)
                balance = available + (arrivals - prediction.daily).cumsum()
                risk = balance.loc[balance < -1e-9]
                risk_date = "" if risk.empty else risk.index[0].date().isoformat()
                urgency = "Риск дефицита" if len(risk) else "Плановый заказ" if quantity > 0 else "Запаса достаточно"
                refs = [f"{snapshot.source_file}/{snapshot.source_sheet}:{snapshot.source_row}", f"{product.source_file}/{product.source_sheet}:{product.source_row}"]
                for source_frame in [sales, monthly, on_time]:
                    if not source_frame.empty:
                        refs.extend(f"{file}/{sheet}" for file, sheet in source_frame[["source_file", "source_sheet"]].drop_duplicates().itertuples(index=False, name=None))
                detail["balance"] = balance
                detail["source_refs"] = refs
                row.update(safety_qty=safety, available_stock=available, stock_as_of=snapshot.as_of.date().isoformat(),
                           stock_source=f"{snapshot.source_file}/{snapshot.source_sheet}:{snapshot.source_row}",
                           inbound_within_horizon=incoming, inbound_late=float(late), inbound_unknown_eta=float(unknown),
                           inbound_overdue=float(overdue), net_need=net, recommended_qty=quantity, urgency=urgency, risk_date=risk_date,
                           source_refs="; ".join(dict.fromkeys(refs)))
                row["explanation"] = (f"На {horizon} дн. прогноз {expected:.2f} {product.unit} + страховой запас {safety:.2f} "
                    f"− доступно {available:.2f} − своевременный путь {incoming:.2f} = потребность {net:.2f}. "
                    f"MOQ {policy.min_order_qty:g}, кратность {policy.order_multiple:g} → заказ {quantity:g} {product.unit}. "
                    f"В истории исключено разового спроса {row['excluded_oneoff_qty']:.2f}, восстановлено {row['imputed_lost_demand']:.2f}. "
                    f"Сезонность: {prediction.seasonal_source}." + (f" Риск дефицита с {risk_date}." if risk_date else ""))
            except ValueError as exc:
                warnings.append(str(exc))
                row["explanation"] = "Расчёт заказа недоступен: " + str(exc)
            row["data_warnings"] = " | ".join(dict.fromkeys(warnings))
            row["assumptions"] = " | ".join(assumptions)
            rows.append(row)
    return Calculation(pd.DataFrame(rows), details, digest, config)
