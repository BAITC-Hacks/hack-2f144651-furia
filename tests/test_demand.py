import pandas as pd
import pytest

from ekt.demand import build_demand, detect_oneoffs


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
