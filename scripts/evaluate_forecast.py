"""Local, deterministic walk-forward diagnostics; not a production API.

Run from the repository: python -m scripts.evaluate_forecast --demo --output report.json
No parameter fitting against holdouts, network access, or synthetic daily targets
derived from monthly totals. See docs/METHODOLOGY.md for assumptions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

# Same source-checkout entry-point convention as scripts/smoke.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from ekt.demand import build_demand, sale_quantities, stockout_mask
from ekt.engine import scoped_optional
from ekt.forecast import forecast
from ekt.schema import KEY, Bundle, fingerprint, normalize, select, validate


MODELS = ("production", "raw_mean", "seasonal_naive")


def _reproducibility():
    root = Path(__file__).resolve().parents[1]
    sources = ["scripts/evaluate_forecast.py", "src/ekt/demand.py", "src/ekt/forecast.py",
               "src/ekt/engine.py", "src/ekt/schema.py", "src/ekt/demo.py", "src/ekt/ingest.py"]
    return {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
            "source_sha256": {name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                              for name in sources}}


def metrics(actual, predicted):
    """WAPE is a ratio, not percent. Undefined denominators are JSON null."""
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape:
        raise ValueError("Actual and predicted shapes differ")
    valid = np.isfinite(actual) & np.isfinite(predicted)
    actual, predicted = actual[valid], predicted[valid]
    error = float(np.abs(actual - predicted).sum())
    denominator = float(np.abs(actual).sum())
    n = len(actual)
    return {"n": n, "absolute_error": error, "absolute_actual": denominator,
            "mae": error / n if n else None,
            "wape": error / denominator if denominator else None,
            "undefined_reason": "no_observations" if not n else "zero_actual_denominator" if not denominator else None}


def _observed_daily(sales, monthly):
    """Invoice coverage assumption matches production; never use imputation as truth."""
    sales = sale_quantities(sales)
    if sales.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    # Missing interior days are zero ONLY under the complete-export assumption.
    dates = pd.date_range(sales.date.min(), sales.date.max())
    raw = sales.groupby("date").quantity_signed.sum().reindex(dates, fill_value=0.)
    for row in monthly.itertuples():
        span = pd.date_range(row.coverage_start, row.coverage_end)
        details = sales.loc[sales.date.between(row.coverage_start, row.coverage_end)]
        raw = raw.reindex(raw.index.union(span))
        if not details.empty and np.isclose(details.quantity_signed.sum(), row.qty_net, rtol=.005, atol=.01):
            raw.loc[span] = details.groupby("date").quantity_signed.sum().reindex(span, fill_value=0.)
        else:
            # Neither uniform monthly allocation nor unreconciled invoices are daily truth.
            raw.loc[span] = np.nan
    return raw.sort_index()


def walk_forward(bundle, cutoffs, horizon=28, stockouts_known_at_end=False):
    """Expanding windows, independent reconstruction at each origin, unchanged model.

    Optional stockout end-date knowledge is an EXPLICIT assumption, not inferred
    metadata. Default: no historical compensation; retrospective censoring only.
    """
    if not isinstance(horizon, int) or horizon < 1 or horizon > 730:
        raise ValueError("horizon must be an integer in 1..730")
    origins = pd.DatetimeIndex(pd.to_datetime(list(cutoffs))).normalize().sort_values()
    if origins.empty or origins.hasnans or origins.duplicated().any():
        raise ValueError("Provide distinct, valid cutoffs")
    bundle = normalize(bundle)
    errors = validate(bundle)
    if errors:
        raise ValueError("\n".join(errors))
    config = {"cutoffs": [d.date().isoformat() for d in origins], "horizon_days": horizon,
              "stockouts_known_at_end": stockouts_known_at_end, "growth_plan": "omitted_no_knowledge_timestamp",
              "seasonal_naive": "same_calendar_date_previous_year; Feb29->Feb28; lag<=cutoff"}
    report = {"format_version": 1, "data_mode": bundle.mode, "config": config,
              "source_data_modes": sorted({str(value) for table in bundle.tables.values() for value in table.data_mode.dropna().unique()}),
              "reproducibility": _reproducibility(),
              "input_fingerprint": fingerprint(bundle, config), "limitations": [
                  "Synthetic data tests reproducibility, not partner accuracy." if bundle.mode == "synthetic" else "Observed sales are not ground truth for latent regular demand.",
                  "Sales event dates / monthly coverage_end are assumed to be availability dates; revisions and ingestion timestamps are absent.",
                  "Missing interior invoice days are assumed zero under a complete-export assumption; missing coverage is never scored.",
                  "Monthly-only or unreconciled monthly coverage is excluded from daily scoring; no allocated or imputed targets.",
                  "Primary comparisons use the same non-stockout target dates for all models; unknown stockouts can still censor sales.",
                  "All-observed scores include censored stockout sales and one-offs; these are sales errors, not latent-demand accuracy.",
                  "Growth plans have no known_as_of and are omitted; current stock, inbound and policies are not forecast inputs here.",
                  "Stockout intervals are retrospective scoring labels. Training uses only completed intervals assumed known at their end." if stockouts_known_at_end else "Stockout knowledge dates are absent: training compensation disabled; intervals used only for retrospective scoring labels.",
                  "No cross-SKU/unit pooling. Overlapping horizons count separate forecast-origin/target pairs.",
              ], "series": []}
    keys = set()
    for name in ("sales", "monthly_sales"):
        keys.update(bundle[name][KEY].itertuples(index=False, name=None))
    for key in sorted(keys):
        product = bundle["products"].loc[bundle["products"].supplier_id.eq(key[0]) & bundle["products"].sku_1c.eq(key[1])].iloc[0]
        sales, monthly, intervals = (select(bundle[name], key) for name in ("sales", "monthly_sales", "stockouts"))
        if pd.isna(product.unit) or (not sales.empty and not sales.unit.eq(product.unit).all()):
            raise ValueError(f"{key}: sales and product units must match")
        truth = _observed_daily(sales, monthly)
        item = {**dict(zip(KEY, key)), "unit": str(product.unit), "folds": []}
        totals = {view: {model: ([], []) for model in MODELS} for view in
                  ("common_available", "production_raw_available", "all_observed")}
        for cutoff in origins:
            fold = {"cutoff": cutoff.date().isoformat()}
            item["folds"].append(fold)
            train_sales = sales.loc[sales.date.le(cutoff)]
            train_monthly = monthly.loc[monthly.month.le(cutoff) & monthly.coverage_end.le(cutoff)]
            train_intervals = intervals.loc[intervals.end_date.le(cutoff)] if stockouts_known_at_end else intervals.iloc[:0]
            # Filter knowledge before category fallback: a future category prior
            # must not shadow a supplier prior available at the historical origin.
            snapshot = Bundle({"seasonal_prior": bundle["seasonal_prior"].loc[
                bundle["seasonal_prior"].known_as_of.le(cutoff)]}, mode=bundle.mode)
            prior = scoped_optional(snapshot, "seasonal_prior", product)
            try:
                demand = build_demand(train_sales, train_monthly, train_intervals, cutoff)
                prediction = forecast(demand, cutoff, horizon, prior=prior, growth=None)
            except ValueError as exc:
                fold.update(status="unavailable", reason=str(exc))
                continue
            dates = prediction.daily.index
            # Baseline uses raw historical quantities, before event exclusion and compensation.
            mean = float(demand.daily.loc[demand.daily.covered, "raw"].mean())
            train_observed = _observed_daily(train_sales, train_monthly)
            lags = pd.DatetimeIndex([d - pd.DateOffset(years=1) for d in dates])
            naive = train_observed.reindex(lags).to_numpy(dtype=float, copy=True)
            naive[lags > cutoff] = np.nan
            frame = pd.DataFrame({"actual": truth.reindex(dates), "production": prediction.daily,
                                  "raw_mean": mean, "seasonal_naive": naive,
                                  "stockout": stockout_mask(dates, intervals)}, index=dates)
            observed = frame.actual.notna()
            available = observed & ~frame.stockout
            common = available & np.isfinite(frame[list(MODELS)]).all(axis=1)
            pair = available & np.isfinite(frame[["production", "raw_mean"]]).all(axis=1)
            fold.update(status="ok", training_end=prediction.training_end,
                        seasonal_source=prediction.seasonal_source,
                        prior_known_as_of=None if prior.empty else prior.known_as_of.max().date().isoformat(),
                        train_excluded_qty=float(demand.daily.excluded.sum()),
                        train_imputed_qty=float(demand.daily.imputed.sum()),
                        n_observed=int(observed.sum()), n_missing=int((~observed).sum()),
                        n_stockout_observed=int((observed & frame.stockout).sum()),
                        n_available=int(available.sum()), n_common=int(common.sum()),
                        warnings=demand.warnings + prediction.warnings, scores={})
            for view, mask in (("common_available", common), ("production_raw_available", pair), ("all_observed", observed)):
                fold["scores"][view] = {}
                for model in MODELS:
                    if view == "production_raw_available" and model == "seasonal_naive":
                        continue
                    valid = mask & np.isfinite(frame[model])
                    actual = frame.loc[valid, "actual"].tolist()
                    predicted = frame.loc[valid, model].tolist()
                    fold["scores"][view][model] = metrics(actual, predicted)
                    totals[view][model][0].extend(actual)
                    totals[view][model][1].extend(predicted)
            # Auditable values (synthetic or user-provided local canonical data); no uploads.
            frame["date"] = frame.index.strftime("%Y-%m-%d")
            fold["predictions"] = json.loads(frame.to_json(orient="records", double_precision=15))
        item["summary"] = {view: {model: metrics(*values) for model, values in models.items()
                                  if not (view == "production_raw_available" and model == "seasonal_naive")}
                           for view, models in totals.items()}
        report["series"].append(item)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="Clearly labelled deterministic synthetic input")
    source.add_argument("--input", type=Path, help="Local canonical ZIP/XLSX (existing ingest contract)")
    parser.add_argument("--mode", choices=("manual", "partner", "synthetic"), default="manual")
    parser.add_argument("--cutoffs", nargs="+", default=["2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31", "2026-08-31"])
    parser.add_argument("--horizon-days", type=int, default=28)
    parser.add_argument("--stockouts-known-at-end", action="store_true", help="Explicit historical knowledge assumption, not supplied by schema")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.demo:
        from ekt.demo import demo_bundle
        bundle = demo_bundle()
    else:
        from ekt.ingest import read_canonical
        bundle = read_canonical(args.input.read_bytes(), args.input.name, mode=args.mode)
    report = walk_forward(bundle, args.cutoffs, args.horizon_days, args.stockouts_known_at_end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{args.output}: {report['data_mode']}, {len(report['series'])} series; no latent-demand accuracy claim")


if __name__ == "__main__":
    main()
