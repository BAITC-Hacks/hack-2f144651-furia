"""Deterministic synthetic data; no partner records."""
import io
import zipfile
import numpy as np
import pandas as pd
from .schema import Bundle, SCHEMAS, normalize

DEMO_DATE = pd.Timestamp("2026-09-22")


def demo_bundle():
    rng = np.random.default_rng(42)
    products = [
        ["IEK", "000001_", "DEMO-CB16", "Автомат 16 А · сезонный спрос", "шт", "A"],
        ["IEK", "000002", "DEMO-CABLE", "Кабель · стабильный рост", "м", "B"],
        ["Systeme", "000001_", "DEMO-SOCKET", "Розетка · разовый заказ клиента", "шт", "A"],
        ["Systeme", "000004", "DEMO-SWITCH", "Выключатель · подтверждённый дефицит", "шт", "B"],
    ]
    tables = {"products": pd.DataFrame(products, columns=SCHEMAS["products"])}
    sales, stock, inbound, stockouts, policies, growth = [], [], [], [], [], []
    dates = pd.date_range("2024-01-01", DEMO_DATE)
    factors = np.array([.70, .72, .85, .95, 1.02, 1.10, 1.03, 1.12, 1.36, 1.46, .96, .73])
    factors /= factors.mean()
    for j, (supplier, sku, _, _, unit, category) in enumerate(products):
        for n, day in enumerate(dates):
            if j == 3 and pd.Timestamp("2026-08-11") <= day <= pd.Timestamp("2026-08-20"):
                continue
            level = [3.5, 12., 4., 6.][j]
            trend = (1 + n / 2200) if j == 1 else 1
            seasonal = factors[day.month - 1] if j == 0 else 1
            quantity = round(level * trend * seasonal * rng.uniform(.85, 1.15), 2)
            sales.append([supplier, sku, "DEMO", day, f"S{j}-{n}", f"anon-{n % 8}", quantity, unit, "sale"])
        stock.append([supplier, sku, "DEMO", DEMO_DATE, [35, 70, 30, 40][j], 5, [30, 65, 25, 35][j], "current"])
        inbound.append([supplier, sku, "DEMO", f"IN-{j}", [20, 50, 10, 20][j], DEMO_DATE + pd.Timedelta(days=4), "expected", "confirmed"])
        inbound.append([supplier, sku, "DEMO", f"LATE-{j}", 500, DEMO_DATE + pd.Timedelta(days=90), "expected", "confirmed"])
    # One anonymous customer splits a single event into three invoices.
    for n in range(3):
        sales.append(["Systeme", "000001_", "DEMO", pd.Timestamp("2026-07-15"), f"ONEOFF-{n}", "anon-project", 350, "шт", "sale"])
    stockouts.append(["Systeme", "000004", "DEMO", "2026-08-11", "2026-08-20", "synthetic_confirmed_interval"])
    for supplier in ["IEK", "Systeme"]:
        for category, safety in [("A", 7), ("B", 3)]:
            policies.append([supplier, category, 14, 7, safety, 0, 1 if category == "B" else 10, "demo"])
    growth.append(["IEK", "000002", None, "2026-09-23", "2027-12-31", .10, "synthetic_growth_plan"])
    for name, records in [("sales", sales), ("stock_snapshots", stock), ("inbound", inbound), ("stockouts", stockouts), ("policies", policies), ("growth_plan", growth)]:
        tables[name] = pd.DataFrame(records, columns=SCHEMAS[name])
    bundle = normalize(Bundle(tables, ["СИНТЕТИЧЕСКИЕ ДАННЫЕ. Все товары, события, остатки и политики созданы для проверки."], "synthetic"))
    # Monthly history is an alternate representation, never extra sales.
    sale = bundle["sales"].copy()
    sale["month"] = sale["date"].dt.to_period("M").dt.to_timestamp()
    monthly = sale.groupby(["supplier_id", "sku_1c", "warehouse_scope", "month"], as_index=False)["quantity_signed"].sum().rename(columns={"quantity_signed": "qty_net"})
    monthly["coverage_start"] = monthly["month"]
    monthly["coverage_end"] = (monthly["month"] + pd.offsets.MonthEnd(0)).clip(upper=DEMO_DATE)
    monthly["is_complete"] = monthly["coverage_end"].eq(monthly["month"] + pd.offsets.MonthEnd(0))
    bundle.tables["monthly_sales"] = monthly
    return normalize(bundle)


def canonical_zip(bundle):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, frame in bundle.tables.items():
            archive.writestr(f"{name}.csv", frame.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8-sig"))
    return buffer.getvalue()
