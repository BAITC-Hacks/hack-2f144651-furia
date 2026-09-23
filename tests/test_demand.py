import pandas as pd
import pytest

from ekt.demand import build_demand, detect_oneoffs, detector_status


def large_events(bundle, customers, dates=("2026-01-01", "2026-01-11", "2026-01-21")):
    extras = bundle["sales"].iloc[:len(customers)].copy()
    extras["date"] = pd.to_datetime(list(dates))
    extras["customer_id"] = customers
    extras["document_id"] = [f"large-{i}" for i in range(len(customers))]
    extras["quantity_signed"] = 1000.
    return pd.concat([bundle["sales"], extras], ignore_index=True)


@pytest.mark.parametrize("customers, excluded", [
    (["one", "two", "three"], 3000),
    (["regular"] * 3, 0),
    ([None] * 3, 3000),
])
def test_e1_customer_identity_controls_recurrence(make_bundle, customers, excluded):
    bundle = make_bundle("2026-01-01", "2026-01-20")
    cleaned, events = detect_oneoffs(large_events(bundle, customers))
    assert cleaned.quantity_signed.sum() == 3200
    assert cleaned.excluded.sum() == excluded
    assert len(events) == excluded // 1000


def test_e1_broad_peak_of_different_customers_is_preserved(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-20")
    cleaned, events = detect_oneoffs(large_events(bundle, ["a", "b", "c"], ["2026-01-11"] * 3))
    assert cleaned.excluded.sum() == 0
    assert events.empty


def test_e1_split_invoices_are_one_customer_day_not_three_visits(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-20")
    cleaned, events = detect_oneoffs(large_events(bundle, ["project"] * 3, ["2026-01-11"] * 3))
    assert cleaned.excluded.sum() == 3000
    assert len(events) == 1
    assert events.iloc[0].quantity == 3000


@pytest.mark.parametrize("count, warning", [(11, True), (12, False)])
def test_e2_threshold_counts_positive_customer_day_events(make_bundle, count, warning):
    bundle = make_bundle("2026-01-01", f"2026-01-{count:02d}", values=[10] * (count - 1) + [1000])
    result = build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], f"2026-01-{count:02d}")
    assert any("12 положительных событий" in w for w in result.warnings) is warning
    assert result.daily.excluded.sum() == (0 if warning else 1000)


def test_e2_split_documents_do_not_satisfy_minimum_history(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-11")
    sales = pd.concat([bundle["sales"], bundle["sales"]], ignore_index=True)
    result = build_demand(sales, bundle["monthly_sales"], bundle["stockouts"], "2026-01-11")
    assert any("11 < 12" in w for w in result.warnings)


def test_disabled_detector_is_explicit(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-11")
    result = build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-01-11", remove_oneoffs=False)
    assert any("отключён" in w for w in result.warnings)
    assert result.events.empty


def test_future_visits_cannot_establish_recurrence_at_cutoff(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-20")
    sales = large_events(bundle, ["regular"] * 3)
    early = build_demand(sales, bundle["monthly_sales"], bundle["stockouts"], "2026-01-15")
    later = build_demand(sales, bundle["monthly_sales"], bundle["stockouts"], "2026-01-21")
    assert early.daily.excluded.sum() == 2000
    assert later.daily.excluded.sum() == 0
    assert early.daily.index.max() == pd.Timestamp("2026-01-15")


def test_partial_month_reconciliation_only_disables_events_inside_coverage(make_bundle):
    from ekt.schema import SCHEMAS, normalize

    bundle = make_bundle("2026-01-01", "2026-01-31")
    bundle.tables["sales"] = large_events(bundle, ["one", "two"], ["2026-01-05", "2026-01-20"])
    bundle.tables["monthly_sales"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-01-01", 200, False, "2026-01-01", "2026-01-10"]
    ], columns=SCHEMAS["monthly_sales"])
    bundle = normalize(bundle)
    result = build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-01-31")
    # 200 authoritative units on days 1–10, 21*10 + 1000 on days 11–31.
    assert result.daily.raw.sum() == 1410
    assert result.daily.excluded.sum() == 1000
    assert result.daily.corrected.sum() == 410
    assert result.events.set_index("date")["applied"].to_dict() == {
        pd.Timestamp("2026-01-05"): False, pd.Timestamp("2026-01-20"): True}
    assert result.events.loc[result.events.applied, "quantity"].sum() == 1000


@pytest.mark.parametrize("count, enabled, status", [
    (11, True, "insufficient_history"), (12, True, "evaluated"),
    (11, False, "disabled"), (12, False, "disabled"),
])
def test_detector_applicability_api_cutoff_and_warning_agree(make_bundle, count, enabled, status):
    bundle = make_bundle("2026-01-01", "2026-01-20")
    sales = pd.concat([bundle["sales"], bundle["sales"]], ignore_index=True)
    before = sales.copy(deep=True)
    cutoff = f"2026-01-{count:02d}"
    assert detector_status(sales, cutoff, enabled) == {
        "status": status, "positive_event_count": count, "minimum_events": 12}
    result = build_demand(sales, bundle["monthly_sales"], bundle["stockouts"], cutoff, remove_oneoffs=enabled)
    assert result.events.empty
    assert any("неприменим" in w for w in result.warnings) == (status == "insufficient_history")
    assert any("отключён" in w for w in result.warnings) == (status == "disabled")
    pd.testing.assert_frame_equal(sales, before)


def test_detector_applicability_excludes_returns_and_uses_document_fallback(make_bundle):
    sales = make_bundle("2026-01-01", "2026-01-12")["sales"].copy()
    sales.loc[0, "document_type"] = "return"  # Positive explicit return is not a positive event.
    sales.loc[1, "quantity_signed"] = 0
    sales.loc[2, "quantity_signed"] = -5
    sales["customer_id"] = None
    sales = pd.concat([sales, sales], ignore_index=True)
    assert detector_status(sales, "2026-01-12")["positive_event_count"] == 9
    assert detector_status(sales.iloc[:0], "2026-01-12") == {
        "status": "insufficient_history", "positive_event_count": 0, "minimum_events": 12}


def test_demand_analytics_conservation_with_events_partial_sales_and_overlapping_stockouts(make_bundle):
    from ekt.forecast import forecast
    from ekt.schema import SCHEMAS, normalize

    bundle = make_bundle("2026-01-01", "2026-01-31")
    bundle.tables["sales"] = large_events(bundle, ["oneoff"], ["2026-01-15"])
    bundle["sales"].loc[bundle["sales"].date.eq("2026-01-21"), "quantity_signed"] = 4
    bundle["sales"].loc[bundle["sales"].date.eq("2026-01-22"), "quantity_signed"] = 0
    bundle.tables["stockouts"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-01-21", "2026-01-22", "confirmed"],
        ["S", "000001_", "W", "2026-01-22", "2026-01-22", "overlap"],
    ], columns=SCHEMAS["stockouts"])
    bundle = normalize(bundle)
    result = build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-01-31")
    assert result.daily.raw.sum() == 1294
    assert result.daily.excluded.sum() == 1000
    assert result.events.loc[result.events.applied, "quantity"].sum() == 1000
    assert result.daily.imputed.sum() == 16  # (10 - 4) + (10 - 0), overlap counted once.
    assert result.daily.corrected.sum() == 310
    for name, expected in [("raw", 1294), ("excluded", 1000), ("imputed", 16), ("corrected", 310)]:
        assert result.monthly[name].sum() == expected
    assert forecast(result, "2026-01-31", 7).daily.sum() == pytest.approx(70)


def test_demand_rejects_overflow_before_missing_aggregate_can_become_zero(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-03", values=[1e308, 1e308, -1e308])
    bundle["sales"]["date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="числов|конеч|диапазон"):
        build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-01-03", remove_oneoffs=False)


def test_demand_rejects_monthly_aggregate_overflow(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-02", values=[1e308, 1e308])
    with pytest.raises(ValueError, match="числов|конеч|диапазон"):
        build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-01-02", remove_oneoffs=False)


def test_unknown_uncovered_days_remain_missing_but_covered_nan_is_rejected(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-02")
    demand = build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-01-04")
    assert demand.daily.loc["2026-01-03":, "corrected"].isna().all()
    assert not demand.daily.loc["2026-01-03":, "covered"].any()
    bundle["sales"].loc[0, "quantity_signed"] = float("nan")
    with pytest.raises(ValueError, match="числов|конеч|диапазон"):
        build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-01-04")
