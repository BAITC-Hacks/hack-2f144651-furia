"""Regular demand, invoice/customer events, and evidenced stockout correction."""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class DemandResult:
    daily: pd.DataFrame
    monthly: pd.DataFrame
    events: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def sale_quantities(sales):
    result = sales.copy()
    kinds = result["document_type"].str.lower().fillna("")
    allowed = kinds.isin(["sale", "return", "расходная накладная", "возврат"])
    result = result.loc[allowed].copy()
    returns = result["document_type"].str.lower().isin(["return", "возврат"])
    # Positive explicit returns reduce sales; signed sales retain their original sign.
    result.loc[returns, "quantity_signed"] = -result.loc[returns, "quantity_signed"].abs()
    return result


def detect_oneoffs(sales, enabled=True):
    frame = sales.copy()
    frame["excluded"] = 0.0
    events = []
    if frame.empty or not enabled:
        return frame, pd.DataFrame(events)
    positive = frame.loc[frame["quantity_signed"] > 0].copy()
    # Anonymous customer + date joins split invoices. Without customer use document,
    # and without either use source row; never invent customer identifiers.
    positive["event_key"] = [
        "customer:" + str(c) if pd.notna(c) else "document:" + str(d) if pd.notna(d) else "row:" + str(i)
        for i, c, d in zip(positive.index, positive["customer_id"], positive["document_id"])
    ]
    groups = positive.groupby(["date", "event_key"], as_index=False)["quantity_signed"].sum()
    if len(groups) < 12:
        return frame, pd.DataFrame(events)
    values = groups["quantity_signed"].to_numpy()
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    threshold = max(5 * median, median + 6 * 1.4826 * mad)
    for _, event in groups.loc[groups["quantity_signed"] > threshold].iterrows():
        quantity = event["quantity_signed"]
        similar = groups.loc[groups["quantity_signed"].between(quantity * .65, quantity * 1.5)]
        # Regular large customers and recurring seasonal order sizes are retained.
        recurring = len(similar) >= 3 and (similar["date"].max() - similar["date"].min()).days >= 14
        same_day = groups.loc[groups["date"].eq(event["date"])]
        broad_peak = (same_day["quantity_signed"] > threshold).sum() >= 3
        if recurring or broad_peak:
            continue
        indices = positive.loc[positive["date"].eq(event["date"]) & positive["event_key"].eq(event["event_key"])].index
        frame.loc[indices, "excluded"] = frame.loc[indices, "quantity_signed"]
        refs = frame.loc[indices]
        events.append({"date": event["date"], "group": event["event_key"], "quantity": quantity,
                       "threshold": threshold, "reason": "Редкое крупное событие; устойчивый порог и проверка повторяемости",
                       "source_refs": "; ".join(f"{r.source_file}/{r.source_sheet}:{r.source_row}" for r in refs.itertuples())})
    return frame, pd.DataFrame(events)


def stockout_mask(index, intervals):
    mask = pd.Series(False, index=index)
    for row in intervals.itertuples():
        # Boolean union prevents double counting intersecting intervals.
        mask |= (index >= row.start_date) & (index <= row.end_date)
    return mask


def build_demand(sales, monthly, stockouts, as_of, remove_oneoffs=True, compensate=True):
    as_of = pd.Timestamp(as_of).normalize()
    warnings = []
    sales = sale_quantities(sales.loc[sales["date"] <= as_of])
    monthly = monthly.loc[(monthly["month"] <= as_of) & (monthly["coverage_end"] <= as_of)].copy()
    sales, events = detect_oneoffs(sales, remove_oneoffs)
    starts = list(sales["date"].dropna()) + list(monthly["coverage_start"].dropna())
    if not starts:
        raise ValueError("Нет истории продаж до даты расчёта")
    start = min(starts)
    if (as_of - start).days > 365 * 15:
        raise ValueError("История больше 15 лет: сократите период импорта")
    index = pd.date_range(start, as_of, freq="D")
    daily = pd.DataFrame(index=index)
    daily.index.name = "date"
    daily["raw"] = np.nan
    daily["excluded"] = 0.0
    daily["stockout"] = stockout_mask(index, stockouts)
    daily["covered"] = False
    # Transactions establish observed coverage only from first to last day.
    if not sales.empty:
        end = sales["date"].max()
        span = (index >= sales["date"].min()) & (index <= end)
        daily.loc[span, "raw"] = 0.0
        daily.loc[span, "covered"] = True
        by_day = sales.groupby("date")[["quantity_signed", "excluded"]].sum()
        daily.loc[by_day.index, "raw"] = by_day["quantity_signed"]
        daily.loc[by_day.index, "excluded"] = by_day["excluded"]
        warnings.append("Дни между первой и последней накладной без строк считаются нулевыми; полнота выгрузки должна быть подтверждена.")
    unapplied_months = []
    for row in monthly.itertuples():
        span = pd.date_range(row.coverage_start, row.coverage_end)
        span = span.intersection(index)
        if len(span) == 0:
            continue
        details = sales.loc[sales["date"].between(row.coverage_start, row.coverage_end)]
        reconciled = not details.empty and np.isclose(details["quantity_signed"].sum(), row.qty_net, rtol=.005, atol=.01)
        if reconciled:
            raw = details.groupby("date")["quantity_signed"].sum().reindex(span, fill_value=0)
            excluded = details.groupby("date")["excluded"].sum().reindex(span, fill_value=0)
            daily.loc[span, "raw"] = raw
            daily.loc[span, "excluded"] = excluded
        else:
            # Monthly history is authoritative. Spread over available dates only;
            # this is an explicitly labelled daily allocation, not actual invoices.
            available = span[~daily.loc[span, "stockout"].to_numpy()]
            allocation_days = available if len(available) else span
            daily.loc[span, "raw"] = 0.0
            daily.loc[allocation_days, "raw"] = row.qty_net / len(allocation_days)
            daily.loc[span, "excluded"] = 0.0
            if not details.empty:
                warnings.append(f"{row.month:%Y-%m}: месячный итог {row.qty_net:g} не сходится с накладными {details.quantity_signed.sum():g}; используется только месячный итог, выбросы из накладных не вычитаются.")
                unapplied_months.append(row.month.to_period("M"))
            else:
                warnings.append("Дневной ряд из месячных итогов распределён равномерно по доступным дням; дневная детализация отсутствует.")
        daily.loc[span, "covered"] = True
    if not events.empty:
        events["applied"] = ~events["date"].dt.to_period("M").isin(unapplied_months)
    daily["regular"] = daily["raw"] - daily["excluded"]
    if (daily["regular"] < 0).any():
        warnings.append("Отрицательный чистый спрос (возвраты) сохранён в истории; итоговый прогноз ограничен снизу нулём.")
    daily["imputed"] = 0.0
    if compensate and daily["stockout"].any():
        # Estimate each censored month from its observed days. Fall back to nearby
        # observed dates only if that month has fewer than seven available days.
        for period in daily.index.to_period("M").unique():
            month_mask = daily.index.to_period("M") == period
            missing = month_mask & daily["stockout"]
            if not missing.any():
                continue
            valid = month_mask & ~daily["stockout"] & daily["covered"]
            if valid.sum() < 7:
                center = period.start_time
                valid = ~daily["stockout"] & daily["covered"] & (daily.index >= center - pd.Timedelta(days=90)) & (daily.index <= center + pd.offsets.MonthEnd(0))
            if not valid.any():
                warnings.append(f"{period}: спрос в stockout не идентифицируется — нет доступных дней")
                continue
            expected = max(0, float(daily.loc[valid, "regular"].mean()))
            observed = daily.loc[missing, "regular"].fillna(0)
            daily.loc[missing, "raw"] = daily.loc[missing, "raw"].fillna(0)
            daily.loc[missing, "regular"] = observed
            daily.loc[missing, "imputed"] = np.maximum(expected - observed, 0)
            daily.loc[missing, "covered"] = True
    daily["corrected"] = daily["regular"] + daily["imputed"]
    summary = daily.groupby(daily.index.to_period("M")).agg(raw=("raw", "sum"), excluded=("excluded", "sum"), imputed=("imputed", "sum"), corrected=("corrected", "sum"), covered_days=("covered", "sum"))
    summary.index = summary.index.to_timestamp()
    summary["days"] = summary.index.days_in_month
    summary["complete"] = (summary["covered_days"] == summary["days"]) & (summary.index + pd.offsets.MonthEnd(0) <= as_of)
    # Explicitly incomplete monthly observations cannot silently become complete.
    incomplete = monthly.loc[~monthly["is_complete"].fillna(False), "month"]
    summary.loc[summary.index.isin(incomplete), "complete"] = False
    return DemandResult(daily, summary, events, list(dict.fromkeys(warnings)))
