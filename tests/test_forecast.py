import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from ekt.demand import build_demand
from ekt.forecast import forecast
from ekt.schema import SCHEMAS, normalize
from scripts.evaluate_forecast import metrics, walk_forward


def first_fold(report, index=0):
    return report["series"][0]["folds"][index]


def predictions(report, index=0):
    return pd.DataFrame(first_fold(report, index)["predictions"])


def test_metrics_numeric_signed_zero_and_missing():
    score = metrics([0, 10, 20], [2, 8, 25])
    assert score == {"n": 3, "absolute_error": 9, "absolute_actual": 30,
                     "mae": 3, "wape": .3, "undefined_reason": None}
    assert metrics([-10, 10], [0, 0])["wape"] == 1
    assert metrics([0, 0], [5, 5])["mae"] == 5
    assert metrics([0, 0], [0, 0])["wape"] is None
    assert metrics([0], [1])["undefined_reason"] == "zero_actual_denominator"
    assert metrics([np.nan], [1])["undefined_reason"] == "no_observations"
    assert metrics([1, 2], [1, np.nan])["n"] == 1
    json.dumps(metrics([0, 0], [5, 5]), allow_nan=False)


def test_walk_forward_constant_all_three_models_and_reproducibility(make_bundle):
    bundle = make_bundle("2024-01-01", "2026-02-28")
    a = walk_forward(bundle, ["2026-01-31", "2025-12-31"], 28)
    b = walk_forward(bundle, ["2025-12-31", "2026-01-31"], 28)
    assert a == b
    assert first_fold(a)["training_end"] == "2025-12-31"
    assert predictions(a).date.iloc[0] == "2026-01-01"
    for model in ("production", "raw_mean", "seasonal_naive"):
        score = a["series"][0]["summary"]["common_available"][model]
        assert score["n"] == 56
        assert score["mae"] == pytest.approx(0, abs=1e-12)
    json.dumps(a, allow_nan=False)


def test_refit_each_origin_without_future_events_or_partial_month(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-31", values=[10] * 10 + [20] * 21)
    report = walk_forward(bundle, ["2026-01-10", "2026-01-20"], 2)
    assert predictions(report).production.tolist() == [10, 10]
    assert predictions(report, 1).production.tolist() == [15, 15]
    assert first_fold(report)["training_end"] == "2026-01-10"
    assert first_fold(report, 1)["training_end"] == "2026-01-20"
    assert first_fold(report)["scores"]["production_raw_available"]["production"]["mae"] == 10
    assert first_fold(report)["scores"]["common_available"]["production"]["n"] == 0


def test_future_sales_monthly_prior_growth_stock_cannot_change_predictions(make_bundle):
    bundle = make_bundle("2025-01-01", "2026-02-28")
    original = predictions(walk_forward(bundle, ["2026-01-15"], 7))
    bundle["sales"].loc[bundle["sales"].date.gt("2026-01-15"), "quantity_signed"] = 9000
    bundle.tables["monthly_sales"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-01-01", 999999, True, "2026-01-01", "2026-01-31"]
    ], columns=SCHEMAS["monthly_sales"])
    bundle.tables["seasonal_prior"] = pd.DataFrame([
        ["S", "A", month, 10 if month == 1 else 1, "2026-01-16", "future"] for month in range(1, 13)
    ], columns=SCHEMAS["seasonal_prior"])
    bundle.tables["growth_plan"] = pd.DataFrame([
        ["S", "000001_", None, "2026-01-01", "2026-12-31", 99, "unknown knowledge date"]
    ], columns=SCHEMAS["growth_plan"])
    bundle["stock_snapshots"]["available"] = 123456
    changed = predictions(walk_forward(bundle, ["2026-01-15"], 7))
    pd.testing.assert_frame_equal(original[["production", "raw_mean", "seasonal_naive"]], changed[["production", "raw_mean", "seasonal_naive"]])


def test_prior_known_on_cutoff_applied_and_input_not_mutated(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-02-10")
    bundle.tables["seasonal_prior"] = pd.DataFrame([
        ["S", "A", month, 2 if month == 2 else 1, "2026-01-31", "known"] for month in range(1, 13)
    ], columns=SCHEMAS["seasonal_prior"])
    bundle = normalize(bundle)
    before = bundle["seasonal_prior"].copy(deep=True)
    report = walk_forward(bundle, ["2026-01-30", "2026-01-31"], 2)
    assert predictions(report).production.tolist() == [10, 10]
    assert predictions(report, 1).production.tolist() == pytest.approx([20, 20])
    assert first_fold(report, 1)["prior_known_as_of"] == "2026-01-31"
    pd.testing.assert_frame_equal(before, bundle["seasonal_prior"])


def test_stockout_targets_are_sales_not_imputed_demand(make_bundle):
    bundle = make_bundle("2024-01-01", "2026-01-03")
    bundle["sales"].loc[bundle["sales"].date.eq("2026-01-02"), "quantity_signed"] = 0
    bundle.tables["stockouts"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-01-02", "2026-01-02", "confirmed"]
    ], columns=SCHEMAS["stockouts"])
    fold = first_fold(walk_forward(bundle, ["2025-12-31"], 3))
    assert fold["n_stockout_observed"] == 1
    assert fold["n_common"] == 2
    assert fold["predictions"][1]["actual"] == 0
    assert fold["scores"]["common_available"]["production"]["mae"] == pytest.approx(0)
    assert fold["scores"]["all_observed"]["production"]["mae"] == pytest.approx(10 / 3)
    assert fold["scores"]["all_observed"]["production"]["wape"] == pytest.approx(.5)


def test_stockout_knowledge_is_explicit_and_intervals_after_cutoff_not_used(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-02-03", values=[10] * 20 + [0] * 10 + [10] * 4)
    bundle.tables["stockouts"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-01-21", "2026-01-30", "confirmed"]
    ], columns=SCHEMAS["stockouts"])
    conservative = first_fold(walk_forward(bundle, ["2026-01-31"], 3))
    assumed = first_fold(walk_forward(bundle, ["2026-01-31"], 3, stockouts_known_at_end=True))
    before_end = first_fold(walk_forward(bundle, ["2026-01-25"], 3, stockouts_known_at_end=True))
    assert conservative["train_imputed_qty"] == 0
    assert assumed["train_imputed_qty"] == 100
    assert assumed["predictions"][0]["production"] == 10
    assert before_end["train_imputed_qty"] == 0


def test_all_stockout_holdout_does_not_claim_demand_accuracy(make_bundle):
    bundle = make_bundle("2024-01-01", "2026-01-03")
    bundle.tables["stockouts"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-01-01", "2026-01-03", "confirmed"]
    ], columns=SCHEMAS["stockouts"])
    fold = first_fold(walk_forward(bundle, ["2025-12-31"], 3))
    assert fold["n_observed"] == 3
    assert fold["n_common"] == 0
    assert fold["scores"]["common_available"]["production"]["mae"] is None


def test_zero_series_wape_is_null_and_missing_holdout_is_not_zero(make_bundle):
    bundle = make_bundle("2024-01-01", "2026-01-03", rate=0)
    fold = first_fold(walk_forward(bundle, ["2025-12-31"], 7))
    assert fold["n_missing"] == 4
    score = fold["scores"]["common_available"]["production"]
    assert score["n"] == 3
    assert score["mae"] == 0
    assert score["wape"] is None


def test_monthly_only_target_not_uniform_daily_truth(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-31")
    bundle.tables["monthly_sales"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-02-01", 280, True, "2026-02-01", "2026-02-28"]
    ], columns=SCHEMAS["monthly_sales"])
    fold = first_fold(walk_forward(bundle, ["2026-01-31"], 28))
    assert fold["n_observed"] == 0
    assert fold["n_missing"] == 28
    assert fold["scores"]["all_observed"]["production"]["mae"] is None


def test_seasonal_naive_calendar_lag_leap_day_and_unavailable_lag(make_bundle):
    bundle = make_bundle("2023-01-01", "2024-03-01")
    bundle["sales"].loc[bundle["sales"].date.eq("2023-02-28"), "quantity_signed"] = 7
    frame = predictions(walk_forward(bundle, ["2024-02-27"], 3))
    assert frame.seasonal_naive.tolist() == [7, 7, 10]
    long = predictions(walk_forward(bundle, ["2023-12-31"], 367))
    assert long.seasonal_naive.iloc[-1] is None or pd.isna(long.seasonal_naive.iloc[-1])


def test_forecast_rejects_demand_built_after_cutoff(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-04-30")
    demand = build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-04-30")
    with pytest.raises(ValueError, match="cutoff"):
        forecast(demand, "2026-02-28", 7)


def test_no_history_reports_unavailable_without_fabricated_scores(make_bundle):
    bundle = make_bundle()
    fold = first_fold(walk_forward(bundle, ["2020-01-01"], 7))
    assert fold["status"] == "unavailable"
    assert "scores" not in fold


def test_duplicate_cutoffs_rejected(make_bundle):
    with pytest.raises(ValueError, match="distinct"):
        walk_forward(make_bundle(), ["2026-01-01", "2026-01-01"])


def test_unreconciled_monthly_targets_are_not_scored(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-02-28")
    bundle.tables["monthly_sales"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-02-01", 9999, True, "2026-02-01", "2026-02-28"]
    ], columns=SCHEMAS["monthly_sales"])
    fold = first_fold(walk_forward(bundle, ["2026-01-31"], 28))
    assert fold["n_observed"] == 0
    assert fold["n_missing"] == 28
    assert fold["predictions"][0]["production"] == 10


def test_known_supplier_prior_fallback_matches_production(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-02-03")
    supplier = [["S", None, m, 2 if m == 2 else 1, "2026-01-31", "known"] for m in range(1, 13)]
    future = [["S", "A", m, 3 if m == 2 else 1, "2026-02-01", "future"] for m in range(1, 13)]
    bundle.tables["seasonal_prior"] = pd.DataFrame(supplier + future, columns=SCHEMAS["seasonal_prior"])
    fold = first_fold(walk_forward(bundle, ["2026-01-31"], 3))
    assert [row["production"] for row in fold["predictions"]] == pytest.approx([20] * 3)
    assert fold["prior_known_as_of"] == "2026-01-31"


def test_forecast_rejects_nonfinite_prior_trend_growth_and_aggregate(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-04-30", rate=10)
    demand = build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-04-30")

    for bad in (np.nan, np.inf):
        prior = pd.DataFrame({"known_as_of": [pd.Timestamp("2026-04-30")] * 12,
                              "month_of_year": range(1, 13), "factor": [bad] * 12,
                              "source": ["synthetic"] * 12})
        with pytest.raises(ValueError, match="prior|коэффициент|конеч"):
            forecast(demand, "2026-04-30", 10, prior=prior)

        broken_trend = type(demand)(demand.daily.copy(), demand.monthly.copy(), demand.events.copy())
        broken_trend.monthly.loc[:, "corrected"] = bad
        with pytest.raises(ValueError, match="тренд|истори|конеч"):
            forecast(broken_trend, "2026-04-30", 10)

        growth = pd.DataFrame({"start_date": [pd.Timestamp("2026-05-01")],
                               "end_date": [pd.Timestamp("2026-05-31")],
                               "extra_growth_rate": [bad]})
        with pytest.raises(ValueError, match="рост|конеч"):
            forecast(demand, "2026-04-30", 10, growth=growth)

    growth = pd.DataFrame({"start_date": [pd.Timestamp("2026-05-01")],
                           "end_date": [pd.Timestamp("2026-05-31")],
                           "extra_growth_rate": [1e307]})
    with pytest.raises(ValueError, match="агрег|горизонт|конеч"):
        forecast(demand, "2026-04-30", 10, growth=growth)


def test_robust_line_median_does_not_overflow_for_constant_finite_history():
    from ekt.forecast import robust_line

    assert robust_line([-3, -2, -1, 0], [1e308] * 4) == (0, 1e308)


def test_unused_extreme_prior_cannot_block_own_seasonality(make_bundle):
    bundle = make_bundle("2024-09-01", "2026-08-31", rate=10)
    demand = build_demand(bundle["sales"], bundle["monthly_sales"], bundle["stockouts"], "2026-08-31")
    expected = forecast(demand, "2026-08-31", 21)
    prior = pd.DataFrame({"known_as_of": [pd.Timestamp("2026-08-31")] * 12,
                          "month_of_year": range(1, 13), "factor": [1e308, 1e-308] * 6,
                          "source": ["synthetic"] * 12})
    actual = forecast(demand, "2026-08-31", 21, prior=prior)
    assert "SKU" in actual.seasonal_source
    pd.testing.assert_series_equal(actual.daily, expected.daily)


def test_local_canonical_cli_runs_outside_pytest_pythonpath(make_bundle, tmp_path):
    from ekt.demo import canonical_zip

    bundle = make_bundle("2026-01-01", "2026-02-03")
    archive, output = tmp_path / "input.zip", tmp_path / "report.json"
    archive.write_bytes(canonical_zip(bundle))
    script = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_forecast.py"
    result = subprocess.run([sys.executable, str(script), "--input", str(archive),
                             "--mode", "synthetic", "--cutoffs", "2026-01-31", "--horizon-days", "3", "--output", str(output)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["data_mode"] == "synthetic"
    assert report["source_data_modes"] == ["synthetic"]
    assert first_fold(report)["scores"]["production_raw_available"]["production"]["mae"] == 0
    assert "src/ekt/forecast.py" in report["reproducibility"]["source_sha256"]


def test_quality_json_coverage_and_pooled_scores_use_observation_weights(make_bundle):
    bundle = make_bundle("2026-01-01", "2026-01-22", values=[10] * 10 + [20] * 12)
    report = walk_forward(bundle, ["2026-01-10", "2026-01-20"], 4)
    early, late = report["series"][0]["folds"]
    # Four errors of 10, then two errors of 5. Two future facts are unknown.
    assert (early["n_observed"], early["n_missing"], early["n_available"], early["n_common"]) == (4, 0, 4, 0)
    assert (late["n_observed"], late["n_missing"], late["n_available"], late["n_common"]) == (2, 2, 2, 0)
    assert [p["actual"] for p in late["predictions"]] == [20, 20, None, None]
    for model in ("production", "raw_mean"):
        score = report["series"][0]["summary"]["production_raw_available"][model]
        assert score["n"] == 6
        assert score["absolute_error"] == pytest.approx(50)
        assert score["absolute_actual"] == 120
        assert score["mae"] == pytest.approx(50 / 6)
        assert score["wape"] == pytest.approx(50 / 120)
    common = report["series"][0]["summary"]["common_available"]["production"]
    assert common["n"] == 0
    assert common["undefined_reason"] == "no_observations"
    assert common["mae"] is None and common["wape"] is None
    json.dumps(report, allow_nan=False)
