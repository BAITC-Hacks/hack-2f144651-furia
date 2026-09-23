import numpy as np
import pandas as pd
import pytest
from ekt.schema import SCHEMAS, normalize, select, KEY
from ekt.engine import calculate
from ekt.demand import build_demand, detect_oneoffs, sale_quantities
from ekt.forecast import forecast
from ekt.demo import demo_bundle


def demand_for(bundle, date):
    key = ("S", "000001_", "W")
    return build_demand(select(bundle["sales"], key), select(bundle["monthly_sales"], key), select(bundle["stockouts"], key), date)


@pytest.mark.parametrize("change", ["history", "lead_time", "growth", "category", "stock", "inbound"])
def test_t4_m1_each_input_changes_result(make_bundle, change):
    bundle = make_bundle()
    original = calculate(bundle, "2026-08-31").rows.iloc[0]
    if change == "history":
        bundle["sales"]["quantity_signed"] *= 1.5
    elif change == "lead_time":
        bundle["policies"].loc[0, "lead_time_days"] += 7
    elif change == "growth":
        bundle.tables["growth_plan"] = pd.DataFrame([["S", "000001_", None, "2026-09-01", "2026-12-31", .5, "demo"]], columns=SCHEMAS["growth_plan"])
    elif change == "category":
        bundle["products"].loc[0, "category_id"] = "B"
    elif change == "stock":
        bundle["stock_snapshots"].loc[0, "available"] = 50
    else:
        bundle.tables["inbound"] = pd.DataFrame([["S", "000001_", "W", "P1", 50, "2026-09-05", "expected", "confirmed"]], columns=SCHEMAS["inbound"])
    result = calculate(bundle, "2026-08-31").rows.iloc[0]
    assert pd.notna(result.recommended_qty)
    if change in ["stock", "inbound"]:
        assert result.recommended_qty < original.recommended_qty
    else:
        assert result.recommended_qty > original.recommended_qty


def test_t5_m2_repeating_sku_seasonality_beats_neutral_prior(make_bundle):
    dates = pd.date_range("2023-01-01", "2025-12-31")
    values = [40 if d.month == 6 else 10 for d in dates]
    bundle = make_bundle("2023-01-01", "2025-12-31", values=values)
    demand = demand_for(bundle, "2025-12-31")
    prior = pd.DataFrame({"month_of_year": range(1, 13), "factor": 1., "known_as_of": pd.Timestamp("2025-12-31"), "source": "neutral"})
    result = forecast(demand, "2025-12-31", 365, prior)
    assert result.daily.loc["2026-06"].mean() > result.daily.loc["2026-01"].mean() * 3
    assert "SKU" in result.seasonal_source


def test_t6_m2_persistent_growth_differs_from_single_spike(make_bundle):
    dates = pd.date_range("2025-01-01", "2026-08-31")
    growth_values = np.linspace(10, 30, len(dates))
    bundle = make_bundle("2025-01-01", "2026-08-31", values=growth_values)
    growing = calculate(bundle, "2026-08-31").rows.iloc[0]
    stable = make_bundle("2025-01-01", "2026-08-31")
    baseline = calculate(stable, "2026-08-31").rows.iloc[0]
    stable["sales"].loc[500, "quantity_signed"] = 1000
    spiky = calculate(stable, "2026-08-31").rows.iloc[0]
    assert growing.expected_demand_horizon > baseline.expected_demand_horizon * 2.5
    assert growing.trend_per_month > 0
    assert abs(spiky.expected_demand_horizon / baseline.expected_demand_horizon - 1) < .1


def test_t7_m3_only_confirmed_days_and_overlap_union(make_bundle):
    values = [10] * 20 + [0] * 10
    bundle = make_bundle("2026-06-01", "2026-06-30", values=values)
    bundle.tables["stockouts"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-06-21", "2026-06-30", "confirmed"],
        ["S", "000001_", "W", "2026-06-25", "2026-06-29", "confirmed"],
    ], columns=SCHEMAS["stockouts"])
    result = calculate(bundle, "2026-06-30")
    daily = next(iter(result.details.values()))["demand"].daily
    assert daily.raw.sum() == 200
    assert daily.imputed.sum() == pytest.approx(100)
    assert daily.corrected.sum() == pytest.approx(300)
    assert daily.stockout.sum() == 10


def test_t8_m3_zero_sales_are_not_evidence_of_stockout(make_bundle):
    bundle = make_bundle("2026-06-01", "2026-06-30", values=[10] * 20 + [0] * 10)
    demand = demand_for(bundle, "2026-06-30")
    assert demand.daily.imputed.sum() == 0
    assert demand.daily.corrected.sum() == 200


def test_t9_m4_one_large_invoice_does_not_inflate_regular_forecast(make_bundle):
    baseline = make_bundle("2026-06-01", "2026-06-30")
    old = calculate(baseline, "2026-06-30").rows.iloc[0]
    baseline["sales"].loc[15, "quantity_signed"] = 1000
    result = calculate(baseline, "2026-06-30").rows.iloc[0]
    assert result.excluded_oneoff_qty == 1000
    assert abs(result.expected_demand_horizon / old.expected_demand_horizon - 1) < .1
    assert baseline["sales"].quantity_signed.sum() > 3 * 300


def test_t10_m4_customer_split_invoices_detected(make_bundle):
    bundle = make_bundle()
    extra = bundle["sales"].iloc[[10]].copy()
    extra["customer_id"] = "anon-special"
    extra["quantity_signed"] = 40
    parts = []
    for i in range(30):
        part = extra.copy()
        part["document_id"] = f"split-{i}"
        parts.append(part)
    bundle.tables["sales"] = pd.concat([bundle["sales"]] + parts, ignore_index=True)
    result = calculate(bundle, "2026-08-31").rows.iloc[0]
    assert result.excluded_oneoff_qty == 1200
    bundle["sales"]["customer_id"] = pd.NA
    no_customer = calculate(bundle, "2026-08-31").rows.iloc[0]
    assert no_customer.excluded_oneoff_qty == 0  # Each document is below robust threshold.
    assert "customer_id" in no_customer.data_warnings


def test_t11_m4_recurring_large_customer_and_broad_peak_retained(make_bundle):
    bundle = make_bundle()
    recurring = bundle["sales"].iloc[::10].copy()
    recurring["customer_id"] = "anon-large-regular"
    recurring["quantity_signed"] = 1000
    recurring["document_id"] = "regular-large"
    extras = []
    for i in range(4):
        row = bundle["sales"].iloc[[30]].copy()
        row["customer_id"] = f"anon-peak-{i}"
        row["quantity_signed"] = 800
        extras.append(row)
    sales = pd.concat([bundle["sales"], recurring] + extras, ignore_index=True)
    cleaned, events = detect_oneoffs(sales)
    assert cleaned.excluded.sum() == 0
    assert events.empty


def test_t12_m5_supplier_keys_and_explanations():
    result = calculate(demo_bundle(), "2026-09-22")
    same_code = result.rows.loc[result.rows.sku_1c.eq("000001_")]
    assert len(same_code) == 2
    assert same_code.supplier_id.nunique() == 2
    assert same_code.row_id.nunique() == 2
    assert result.rows[["explanation", "urgency", "unit", "source_refs"]].notna().all().all()


def test_partial_stockout_adds_only_unobserved_demand(make_bundle):
    bundle = make_bundle("2026-06-01", "2026-06-30", values=[10] * 20 + [2] * 10)
    bundle.tables["stockouts"] = pd.DataFrame([["S", "000001_", "W", "2026-06-21", "2026-06-30", "confirmed"]], columns=SCHEMAS["stockouts"])
    bundle = normalize(bundle)
    demand = demand_for(bundle, "2026-06-30")
    assert demand.daily.raw.sum() == 220
    assert demand.daily.imputed.sum() == 80
    assert demand.daily.corrected.sum() == 300


def test_returns_receipts_and_pending_orders_are_not_sales(make_bundle):
    bundle = make_bundle("2026-06-01", "2026-06-30")
    sales = bundle["sales"].iloc[:5].copy()
    sales["quantity_signed"] = [10, -3, 7, 100, 200]
    sales["document_type"] = ["sale", "sale", "return", "receipt", "customer_order"]
    normalized = sale_quantities(sales)
    assert normalized.quantity_signed.sum() == 0
