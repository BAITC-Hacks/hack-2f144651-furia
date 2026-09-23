import pandas as pd
import pytest

from ekt.engine import calculate
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
