"""Calendar seasonality with a robust trend; no API or future observations."""
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class ForecastResult:
    daily: pd.Series
    seasonal_factors: dict
    seasonal_source: str
    slope_per_month: float
    training_end: str
    warnings: list[str]


def robust_line(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    slopes = [(y[j] - y[i]) / (x[j] - x[i]) for i in range(len(x)) for j in range(i + 1, len(x)) if x[j] - x[i] >= 2]
    slope = float(np.median(slopes)) if slopes else 0.0
    intercept = float(np.median(y - slope * x))
    return slope, intercept


def forecast(demand, as_of, horizon, prior=None, growth=None):
    as_of = pd.Timestamp(as_of)
    if (demand.daily.index > as_of).any() or (
        demand.monthly.loc[demand.monthly["complete"]].index + pd.offsets.MonthEnd(0) > as_of
    ).any():
        raise ValueError("История построена позже cutoff: вызовите build_demand заново на дату прогноза")
    dates = pd.date_range(as_of + pd.Timedelta(days=1), periods=horizon, freq="D")
    months = demand.monthly.loc[demand.monthly["complete"]].tail(48)
    warnings = []
    factors = np.ones(12)
    seasonal_source = "Нейтральная сезонность: недостаточно полных циклов"
    if prior is not None and not prior.empty:
        selected = prior.loc[prior["known_as_of"] <= as_of]
        if not selected.empty:
            selected = selected.loc[selected["known_as_of"].eq(selected["known_as_of"].max())]
            if len(selected) == 12:
                factors = selected.sort_values("month_of_year")["factor"].to_numpy(dtype=float, copy=True)
                factors /= factors.mean()
                seasonal_source = "Внешний prior: " + str(selected.iloc[0]["source"])
    counts = pd.Series(months.index.month).value_counts()
    own_seasonality = len(counts) == 12 and counts.min() >= 2
    if len(months) < 3:
        observations = demand.daily.loc[demand.daily["covered"], "corrected"]
        if observations.empty:
            raise ValueError("Недостаточно наблюдаемых доступных дней")
        # Short history remains usable, but cannot claim a measured trend.
        rate = max(0, float(observations.mean()))
        mean_season = np.mean([factors[d.month - 1] for d in observations.index])
        values = np.array([rate / mean_season * factors[d.month - 1] for d in dates])
        slope = 0.0
        training_end = observations.index.max().date().isoformat()
        warnings.append("Меньше трёх полных месяцев: средний дневной спрос без оценки тренда.")
    else:
        x = np.array([d.year * 12 + d.month for d in months.index], dtype=float)
        origin = x[-1]
        x -= origin
        rates = months["corrected"].clip(lower=0).to_numpy() / months["days"].to_numpy()
        month_idx = months.index.month.to_numpy() - 1
        if own_seasonality:
            factors = np.ones(12)
            # Alternating robust trend and calendar factors separates sustained
            # change from repeated yearly peaks with a small transparent model.
            for _ in range(5):
                slope, intercept = robust_line(x, rates / factors[month_idx])
                trend = np.maximum(intercept + slope * x, max(np.mean(rates) * .05, .001))
                ratio = rates / trend
                factors = np.array([max(.05, np.median(ratio[month_idx == m])) for m in range(12)])
                factors /= factors.mean()
            seasonal_source = "Календарный профиль SKU (≥2 полных циклов)"
        slope, intercept = robust_line(x[-24:], (rates / factors[month_idx])[-24:])
        cap = max(abs(intercept) * .25, .001)
        if abs(slope) > cap:
            slope = float(np.clip(slope, -cap, cap))
            warnings.append("Тренд ограничен ±25% последнего дневного уровня за месяц; инженерное ограничение MVP.")
        values = []
        for day in dates:
            future_x = day.year * 12 + day.month - origin + (day.day - .5) / day.days_in_month - .5
            values.append(max(0, intercept + slope * future_x) * factors[day.month - 1])
        values = np.asarray(values)
        training_end = (months.index[-1] + pd.offsets.MonthEnd(0)).date().isoformat()
    if growth is not None and not growth.empty:
        for i, day in enumerate(dates):
            active = growth.loc[(growth["start_date"] <= day) & (growth["end_date"] >= day)]
            # At most one applicable plan per day; conflicting plans are explicit.
            if len(active) > 1:
                raise ValueError("Пересекаются планы роста для одной позиции")
            if len(active) == 1:
                values[i] *= 1 + float(active.iloc[0]["extra_growth_rate"])
    return ForecastResult(pd.Series(np.maximum(values, 0), index=dates, name="forecast"), {m + 1: float(v) for m, v in enumerate(factors)}, seasonal_source, float(slope), training_end, warnings)
