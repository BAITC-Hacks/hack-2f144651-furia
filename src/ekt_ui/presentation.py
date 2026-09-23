"""Read-only view models. Purchase quantities and rules remain in ekt."""
import numpy as np
import pandas as pd

from ekt.schema import KEY


def number(value, digits=1):
    if value is None or pd.isna(value):
        return "Нет данных"
    return f"{value:,.{digits}f}".replace(",", " ").rstrip("0").rstrip(".") if digits else f"{value:,.0f}".replace(",", " ")


def urgency_label(row, as_of):
    if pd.isna(row.recommended_qty):
        return "Нужны данные"
    risk_date = pd.to_datetime(row.get("risk_date"), errors="coerce")
    if pd.notna(risk_date) and (risk_date - pd.Timestamp(as_of)).days < 7:
        return "Критично"
    if row.urgency == "Риск дефицита" or row.recommended_qty > 0:
        return "Пополнение"
    return "Норма"


def manual_mask(rows):
    final = rows.adjusted_qty.where(rows.adjusted_qty.notna(), rows.recommended_qty)
    return rows.recommended_qty.notna() & ~np.isclose(
        final.to_numpy(dtype=float, na_value=np.nan),
        rows.recommended_qty.to_numpy(dtype=float, na_value=np.nan),
    )


def order_grid(calculation, edits):
    rows = calculation.rows.merge(edits, on="row_id", validate="one_to_one")
    rows["priority"] = rows.apply(urgency_label, axis=1, as_of=calculation.config["as_of"])
    rows["manual_edit"] = np.where(manual_mask(rows), "Ручная правка", "")
    rows["history"] = [
        calculation.details[row_id]["demand"].monthly["raw"].tail(6).tolist()
        if row_id in calculation.details else []
        for row_id in rows.row_id
    ]
    for field in ("available_stock", "inbound_within_horizon", "expected_demand_horizon"):
        if field not in rows:
            rows[field] = np.nan
    return rows


def filter_orders(rows, suppliers, scopes, categories, risk="Все", search=""):
    mask = (rows.supplier_id.isin(suppliers) & rows.warehouse_scope.isin(scopes)
            & rows.category_id.fillna("Не указана").isin(categories))
    if risk == "Риск дефицита":
        mask &= rows.urgency.eq("Риск дефицита")
    elif risk == "Ручные правки":
        mask &= rows.manual_edit.ne("")
    elif risk != "Все":
        mask &= rows.priority.eq(risk)
    query = search.strip()
    if query:
        matches = pd.Series(False, index=rows.index)
        for column in ("sku_1c", "supplier_sku", "name"):
            matches |= rows[column].astype("string").str.contains(query, case=False, regex=False, na=False)
        mask &= matches
    return rows.loc[mask].copy()


def merge_visible_edits(all_edits, visible_edits):
    merged = all_edits.set_index("row_id").copy()
    visible = visible_edits.set_index("row_id")
    for column in ("selected", "adjusted_qty", "reason"):
        merged.loc[visible.index, column] = visible[column]
    return merged.reset_index()[all_edits.columns]


def deliveries(bundle, as_of):
    frame = bundle["inbound"].copy()
    # Ambiguous product keys cannot provide a trustworthy name or unit.
    products = bundle["products"].drop_duplicates(["supplier_id", "sku_1c"], keep=False)
    frame = frame.merge(products[["supplier_id", "sku_1c", "name", "unit"]], on=["supplier_id", "sku_1c"], how="left")
    frame["delivery_state"] = "Неизвестный статус"
    confirmed = frame.status.eq("confirmed")
    frame.loc[confirmed & frame.eta.gt(pd.Timestamp(as_of)), "delivery_state"] = "Ожидается"
    frame.loc[confirmed & frame.eta.le(pd.Timestamp(as_of)), "delivery_state"] = "Просрочена"
    frame.loc[confirmed & frame.eta.isna(), "delivery_state"] = "Нет ETA"
    frame.loc[frame.status.eq("pending"), "delivery_state"] = "Не подтверждена"
    frame.loc[frame.status.eq("cancelled"), "delivery_state"] = "Отменена"
    return frame.sort_values("eta", na_position="last")


def item_deliveries(bundle, row):
    frame = deliveries(bundle, row.as_of)
    mask = pd.Series(True, index=frame.index)
    for field in KEY:
        mask &= frame[field].eq(row[field]).fillna(False)
    return frame.loc[mask]
