import pandas as pd
import pytest

from ekt.engine import calculate, classify_risk
from ekt.schema import SCHEMAS


def test_e2_short_history_warning_reaches_recommendation(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-11", values=[10] * 10 + [1000])
    result = calculate(bundle, "2026-01-11")
    row = result.rows.iloc[0]
    assert row.excluded_oneoff_qty == 0
    assert row.expected_demand_horizon == pytest.approx(2100)
    assert row.recommended_qty == 2300
    assert "11 < 12" in row.data_warnings
    assert "не доказывает отсутствие аномалий" in row.data_warnings


def test_future_category_prior_must_not_shadow_known_supplier_prior(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-31")
    supplier = [["S", None, m, 2 if m == 2 else 1, "2026-01-31", "known supplier"] for m in range(1, 13)]
    bundle.tables["seasonal_prior"] = pd.DataFrame(supplier, columns=SCHEMAS["seasonal_prior"])
    original = calculate(bundle, "2026-01-31").rows.iloc[0]
    future = [["S", "A", m, 3 if m == 2 else 1, "2026-02-01", "future category"] for m in range(1, 13)]
    bundle.tables["seasonal_prior"] = pd.DataFrame(supplier + future, columns=SCHEMAS["seasonal_prior"])
    changed = calculate(bundle, "2026-01-31").rows.iloc[0]
    assert original.expected_demand_horizon == pytest.approx(420)
    assert changed.expected_demand_horizon == pytest.approx(420)
    assert changed.seasonal_source == original.seasonal_source


def test_e3_growth_plan_applied_once_after_regular_forecast(make_bundle):
    bundle = make_bundle(rate=10)
    baseline = calculate(bundle, "2026-08-31").rows.iloc[0]
    bundle.tables["growth_plan"] = pd.DataFrame([
        ["S", "000001_", None, "2026-09-01", "2026-09-30", .5, "synthetic"]
    ], columns=SCHEMAS["growth_plan"])
    grown = calculate(bundle, "2026-08-31").rows.iloc[0]
    assert baseline.expected_demand_horizon == pytest.approx(210)
    assert grown.expected_demand_horizon == pytest.approx(315)
    assert grown.safety_qty == pytest.approx(30)
    assert grown.recommended_qty == 345


@pytest.mark.parametrize("available, risk_day, net, order", [(30, 6, 65, 84), (40, 7, 55, 84)])
def test_dashboard_components_and_risk_boundaries(make_bundle, available, risk_day, net, order):
    from ekt_ui.presentation import urgency_label

    bundle = make_bundle(rate=10)
    bundle["policies"].loc[:, ["lead_time_days", "review_days", "safety_days", "min_order_qty", "order_multiple"]] = [7, 3, 2, 80, 6]
    bundle["stock_snapshots"].loc[:, ["on_hand", "reserved", "available"]] = [available + 20, 20, available]
    bundle.tables["inbound"] = pd.DataFrame([
        ["S", "000001_", "W", "ontime", 25, "2026-09-04", "confirmed", "confirmed"],
        ["S", "000001_", "W", "late", 100, "2026-09-11", "confirmed", "confirmed"],
        ["S", "000001_", "W", "unknown", 200, None, "unknown", "confirmed"],
        ["S", "000001_", "W", "overdue", 300, "2026-08-31", "confirmed", "confirmed"],
        ["S", "000001_", "W", "pending", 400, "2026-09-01", "confirmed", "pending"],
        ["S", "000001_", "W", "cancelled", 500, "2026-09-01", "confirmed", "cancelled"],
    ], columns=SCHEMAS["inbound"])
    calculation = calculate(bundle, "2026-08-31")
    row = calculation.rows.iloc[0]
    detail = calculation.details[row.row_id]
    assert row.expected_demand_horizon == pytest.approx(100)
    assert row.safety_qty == pytest.approx(20)
    assert row.available_stock == available  # reserve already removed exactly once.
    assert row.inbound_within_horizon == 25
    assert (row.inbound_late, row.inbound_unknown_eta, row.inbound_overdue) == (100, 200, 300)
    assert row.net_need == pytest.approx(net)
    assert row.recommended_qty == order  # MOQ 80, rounded up to a multiple of 6.
    assert detail["forecast"].daily.tolist() == pytest.approx([10] * 10)
    assert detail["balance"].tolist() == pytest.approx([
        available - 10, available - 20, available - 30, available - 15,
        available - 25, available - 35, available - 45, available - 55, available - 65, available - 75])
    assert row.risk_date == f"2026-09-{risk_day:02d}"
    for fragment in ["прогноз 100.00", "запас 20.00", f"доступно {available:.2f}",
                     "путь 25.00", f"потребность {net:.2f}", "MOQ 80, кратность 6 → заказ 84", row.risk_date]:
        assert fragment in row.explanation
    before = row.copy(deep=True)
    assert classify_risk(row, "2026-08-31") == {
        "risk_level": "critical" if risk_day == 6 else "risk", "days_to_risk": risk_day,
        "calculation_status": "calculated", "order_required": True}
    assert urgency_label(row, "2026-08-31") == ("Критично" if risk_day == 6 else "Пополнение")
    pd.testing.assert_series_equal(row, before)


@pytest.mark.parametrize("available, inbound, safety, quantity, level", [
    (0, 100, 0, 0, "critical"),  # Arrival on day 10 covers net need, but not interim deficit.
    (100, 0, 2, 20, "none"),    # Safety replenishment does not mean a predicted deficit.
    (200, 0, 2, 0, "none"),
])
def test_risk_and_order_required_are_independent(make_bundle, available, inbound, safety, quantity, level):
    bundle = make_bundle()
    bundle["policies"].loc[:, ["lead_time_days", "review_days", "safety_days"]] = [7, 3, safety]
    bundle["stock_snapshots"].loc[:, ["on_hand", "reserved", "available"]] = [available, 0, available]
    bundle.tables["inbound"] = pd.DataFrame([
        ["S", "000001_", "W", "lastday", inbound, "2026-09-10", "confirmed", "confirmed"]
    ], columns=SCHEMAS["inbound"])
    calculation = calculate(bundle, "2026-08-31")
    row = calculation.rows.iloc[0]
    assert row.recommended_qty == quantity
    assert classify_risk(row, "2026-08-31") == {
        "risk_level": level, "days_to_risk": 1 if inbound else None,
        "calculation_status": "calculated", "order_required": quantity > 0}
    warnings_changed = row.copy()
    warnings_changed["data_warnings"] = "Неизвестные customer_id, stockout, цены"
    assert classify_risk(warnings_changed, "2026-08-31") == classify_risk(row, "2026-08-31")


def test_forecast_without_stock_is_not_a_completed_order_calculation(make_bundle):
    bundle = make_bundle()
    bundle.tables["stock_snapshots"] = bundle["stock_snapshots"].iloc[:0]
    calculation = calculate(bundle, "2026-08-31")
    row = calculation.rows.iloc[0]
    assert row.expected_demand_horizon == pytest.approx(210)
    assert "forecast" in calculation.details[row.row_id]
    assert pd.isna(row.recommended_qty)
    assert classify_risk(row, "2026-08-31") == classify_risk(None, "2026-08-31") == {
        "risk_level": "unknown", "days_to_risk": None,
        "calculation_status": "unavailable", "order_required": None}


def test_row_id_is_unambiguous_for_pipe_characters(make_bundle):
    from ekt.review import approve, export_frame, initial_edits

    first, second = make_bundle(), make_bundle(rate=20)
    for bundle, sku, scope in [(first, "X|Y", "Z"), (second, "X", "Y|Z")]:
        for frame in bundle.tables.values():
            if "sku_1c" in frame:
                frame["sku_1c"] = sku
            if "warehouse_scope" in frame:
                frame["warehouse_scope"] = scope
    for name in ["products", "sales", "stock_snapshots"]:
        first.tables[name] = pd.concat([first[name], second[name]], ignore_index=True)

    calculation = calculate(first, "2026-08-31")
    assert len(calculation.rows) == len(calculation.details) == 2
    assert calculation.rows.row_id.nunique() == 2
    assert calculate(first, "2026-08-31").rows.row_id.tolist() == calculation.rows.row_id.tolist()
    edits = initial_edits(calculation.rows)
    edits["reason"] = "separate composite key"
    approval = approve(calculation, edits)
    exported = export_frame(calculation, edits, approval)
    assert exported.row_id.nunique() == 2
    assert exported.approval_status.eq("approved").all()


def test_extreme_finite_prior_does_not_turn_positive_demand_into_zero(make_bundle):
    from ekt.schema import SCHEMAS

    bundle = make_bundle(rate=10)
    bundle["stock_snapshots"].loc[:, ["on_hand", "reserved", "available"]] = [0, 0, 0]
    bundle.tables["seasonal_prior"] = pd.DataFrame(
        [["S", "A", month, 1e308, "2026-08-31", "synthetic"] for month in range(1, 13)],
        columns=SCHEMAS["seasonal_prior"],
    )
    row = calculate(bundle, "2026-08-31").rows.iloc[0]
    assert row.expected_demand_horizon == pytest.approx(210)
    assert row.recommended_qty > 0


def test_tiny_order_multiple_is_a_controlled_numeric_error():
    from ekt.engine import order_quantity

    with pytest.raises(ValueError, match="кратност|точност"):
        order_quantity(10, 0, 0, 0, 1e-308)
    assert order_quantity(1e-8, 0, 0, 0, 1e8) == (1e-8, 1e8)
    assert order_quantity(1.7e308, 0, 0, 0, 1.0) == (1.7e308, 1.7e308)
    with pytest.raises(ValueError, match="кратностей|диапазон"):
        order_quantity(1.7e308, 0, 0, 0, 1e-8)


def test_order_rounding_does_not_remove_a_supported_fractional_need():
    from ekt.engine import order_quantity

    assert order_quantity(100000000.00000001, 0, 0, 0, 1)[1] == 100000001
    assert order_quantity(.07, 0, 0, 0, .01)[1] == .07
    assert order_quantity(.3, 0, .1, 0, .1)[1] == .2
    assert order_quantity(1e17, 0, 0, 0, .3)[1] >= 1e17
    assert order_quantity(1e15, 0, 0, 0, 1e-8)[1] >= 1e15
    assert order_quantity(1e-11, 0, 0, 0, 1) == (1e-11, 1)
    assert order_quantity(.1, .2, .3, 0, 1) == (0, 0)
    with pytest.raises(ValueError, match="кратност|Кратност|точност"):
        order_quantity(4.5e-8, 0, 0, 0, 1.5e-8)


@pytest.mark.parametrize("horizon,safety,expected", [(7, 2, .9), (14, 2, 1.6), (21, 2, 2.3), (30, 3, 3.3)])
def test_fractional_order_arithmetic_does_not_add_a_pack_from_float_noise(make_bundle, horizon, safety, expected):
    from ekt.engine import order_quantity

    assert order_quantity(.1, .2, 0, 0, .1) == (.3, .3)
    assert order_quantity(.4, 0, .1, 0, .1) == (.3, .3)
    bundle = make_bundle(rate=.1)
    bundle["policies"]["order_multiple"] = .1
    bundle["policies"]["lead_time_days"] = horizon
    bundle["policies"]["review_days"] = 0
    bundle["policies"]["safety_days"] = safety
    row = calculate(bundle, "2026-08-31").rows.iloc[0]
    assert row.recommended_qty == expected


def test_real_small_sales_change_crosses_pack_boundary(make_bundle):
    bundle = make_bundle(rate=10)
    assert calculate(bundle, "2026-08-31").rows.iloc[0].recommended_qty == 230
    bundle["sales"]["quantity_signed"] = 10.00000000004
    assert calculate(bundle, "2026-08-31").rows.iloc[0].recommended_qty == 231


def test_nonfinite_projected_balance_makes_order_unavailable(make_bundle):
    from ekt.schema import SCHEMAS

    bundle = make_bundle("2026-08-31", "2026-08-31", rate=7e306)
    bundle["policies"]["safety_days"] = 0
    bundle["stock_snapshots"].loc[:, ["on_hand", "reserved", "available"]] = [1.5e308, 0, 1.5e308]
    bundle.tables["inbound"] = pd.DataFrame(
        [["S", "000001_", "W", "large-arrival", 1.5e308, "2026-09-01", "confirmed", "confirmed"]],
        columns=SCHEMAS["inbound"],
    )
    row = calculate(bundle, "2026-08-31").rows.iloc[0]
    assert pd.isna(row.recommended_qty)
    assert row.urgency == "Нужны данные"
    assert "остат" in row.explanation


def test_nonfinite_safety_makes_order_unavailable(make_bundle):
    bundle = make_bundle("2026-08-31", "2026-08-31", rate=7e306)
    bundle["policies"]["safety_days"] = 30
    row = calculate(bundle, "2026-08-31").rows.iloc[0]
    assert pd.isna(row.recommended_qty)
    assert row.urgency == "Нужны данные"
    assert "числов" in row.explanation


@pytest.mark.parametrize("row, level, days, status, required", [
    ({"recommended_qty": 0, "risk_date": "2026-08-30"}, "critical", -1, "calculated", False),
    ({"recommended_qty": 0, "risk_date": "2026-08-31"}, "critical", 0, "calculated", False),
    ({"recommended_qty": None, "risk_date": "2026-09-01"}, "unknown", None, "unavailable", None),
    ({"recommended_qty": float("inf")}, "unknown", None, "unavailable", None),
    ({"recommended_qty": 0, "risk_date": "invalid"}, "unknown", None, "calculated", False),
    ({"recommended_qty": 0, "urgency": "Риск дефицита"}, "risk", None, "calculated", False),
    ({"recommended_qty": 0, "urgency": pd.NA}, "unknown", None, "calculated", False),
])
def test_risk_unknown_and_undated_deficit_are_explicit(row, level, days, status, required):
    assert classify_risk(row, "2026-08-31") == {
        "risk_level": level, "days_to_risk": days, "calculation_status": status, "order_required": required}


@pytest.mark.parametrize("cutoff", [None, pd.NaT, ""])
def test_helper_apis_require_an_explicit_calculation_date(make_bundle, cutoff):
    from ekt.demand import detector_status

    with pytest.raises(ValueError, match="Нужна дата"):
        classify_risk(None, cutoff)
    with pytest.raises(ValueError, match="Нужна дата"):
        detector_status(make_bundle()["sales"], cutoff)
