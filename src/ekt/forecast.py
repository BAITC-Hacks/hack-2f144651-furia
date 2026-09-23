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


def _finite(name, values):
    try:
        values = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: ожидаются числовые значения") from exc
    if not np.isfinite(values).all():
        raise ValueError(f"{name}: результат выходит за поддерживаемый конечный числовой диапазон")
    return values


def _stable_mean(values):
    values = _finite("Среднее", values)
    if values.size == 0:
        raise ValueError("Недостаточно наблюдений для прогноза")
    scale = float(np.max(np.abs(values)))
    if scale == 0:
        return 0.0
    return float(scale * np.mean(values / scale))


def _stable_median(values):
    values = np.sort(_finite("Медиана", values))
    if values.size == 0:
        raise ValueError("Недостаточно наблюдений для прогноза")
    middle = values.size // 2
    if values.size % 2:
        return float(values[middle])
    left, right = float(values[middle - 1]), float(values[middle])
    pair_sum = left + right
    return pair_sum / 2 if np.isfinite(pair_sum) else left / 2 + right / 2


def _normalize_factors(values):
    factors = _finite("Сезонный prior", values)
    if factors.size != 12 or (factors <= 0).any():
        raise ValueError("Сезонный prior должен содержать 12 конечных положительных коэффициентов")
    scale = float(np.max(factors))
    scaled = factors / scale
    mean = float(np.mean(scaled))
    if not np.isfinite(mean) or mean <= 0 or (scaled <= 0).any():
        raise ValueError("Сезонный prior выходит за поддерживаемую точность нормализации")
    normalized = scaled / mean
    if not np.isfinite(normalized).all() or (normalized <= 0).any():
        raise ValueError("Сезонный prior выходит за поддерживаемый диапазон нормализации")
    return normalized


def robust_line(x, y):
    x, y = _finite("Ось тренда", x), _finite("История для тренда", y)
    if x.shape != y.shape:
        raise ValueError("История для тренда имеет неверный размер")
    slopes = []
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        for i in range(len(x)):
            for j in range(i + 1, len(x)):
                distance = x[j] - x[i]
                if distance >= 2:
                    difference = y[j] - y[i]
                    slope = difference / distance
                    if not np.isfinite(difference) or not np.isfinite(slope):
                        raise ValueError("Тренд выходит за поддерживаемый конечный числовой диапазон")
                    slopes.append(slope)
    slope = _stable_median(slopes) if slopes else 0.0
    with np.errstate(over="ignore", invalid="ignore"):
        residuals = y - slope * x
    _finite("Уровень тренда", residuals)
    intercept = _stable_median(residuals)
    if not np.isfinite(slope) or not np.isfinite(intercept):
        raise ValueError("Тренд выходит за поддерживаемый конечный числовой диапазон")
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
    counts = pd.Series(months.index.month).value_counts()
    own_seasonality = len(counts) == 12 and counts.min() >= 2
    if not own_seasonality and prior is not None and not prior.empty:
        selected = prior.loc[prior["known_as_of"] <= as_of]
        if not selected.empty:
            selected = selected.loc[selected["known_as_of"].eq(selected["known_as_of"].max())]
            if len(selected) == 12:
                factors = _normalize_factors(selected.sort_values("month_of_year")["factor"].to_numpy(dtype=float, copy=True))
                seasonal_source = "Внешний prior: " + str(selected.iloc[0]["source"])
    if len(months) < 3:
        observations = demand.daily.loc[demand.daily["covered"], "corrected"]
        if observations.empty:
            raise ValueError("Недостаточно наблюдаемых доступных дней")
        rate = max(0, _stable_mean(observations.to_numpy(dtype=float)))
        mean_season = _stable_mean(np.array([factors[d.month - 1] for d in observations.index]))
        if mean_season <= 0:
            raise ValueError("Сезонные коэффициенты не имеют положительного среднего")
        values = np.array([rate / mean_season * factors[d.month - 1] for d in dates])
        slope = 0.0
        training_end = observations.index.max().date().isoformat()
        warnings.append("Меньше трёх полных месяцев: средний дневной спрос без оценки тренда.")
    else:
        x = np.array([d.year * 12 + d.month for d in months.index], dtype=float)
        origin = x[-1]
        x -= origin
        days = months["days"].to_numpy(dtype=float)
        if not np.isfinite(days).all() or (days <= 0).any():
            raise ValueError("История для прогноза содержит неверное число дней")
        corrected = _finite("История спроса", months["corrected"].to_numpy(dtype=float))
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            rates = np.maximum(corrected / days, 0)
        _finite("Дневной уровень истории", rates)
        month_idx = months.index.month.to_numpy() - 1
        if own_seasonality:
            factors = np.ones(12)
            # Alternating robust trend and calendar factors separates sustained
            # change from repeated yearly peaks with a small transparent model.
            for _ in range(5):
                with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                    deseasonalized = rates / factors[month_idx]
                _finite("История после сезонной корректировки", deseasonalized)
                slope, intercept = robust_line(x, deseasonalized)
                trend_floor = max(_stable_mean(rates) * .05, .001)
                with np.errstate(over="ignore", invalid="ignore"):
                    trend = np.maximum(intercept + slope * x, trend_floor)
                    ratio = rates / trend
                _finite("Тренд для сезонности", trend)
                _finite("Отношение к тренду", ratio)
                factors = np.array([max(.05, _stable_median(ratio[month_idx == m])) for m in range(12)])
                factors = _normalize_factors(factors)
            seasonal_source = "Календарный профиль SKU (≥2 полных циклов)"
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            detrended_rates = rates / factors[month_idx]
        _finite("История для тренда", detrended_rates)
        slope, intercept = robust_line(x[-24:], detrended_rates[-24:])
        cap = max(abs(intercept) * .25, .001)
        if not np.isfinite(cap):
            raise ValueError("Ограничение тренда выходит за поддерживаемый диапазон")
        if abs(slope) > cap:
            slope = float(np.clip(slope, -cap, cap))
            warnings.append("Тренд ограничен ±25% последнего дневного уровня за месяц; инженерное ограничение MVP.")
        values = []
        for day in dates:
            future_x = day.year * 12 + day.month - origin + (day.day - .5) / day.days_in_month - .5
            with np.errstate(over="ignore", invalid="ignore"):
                trend_value = intercept + slope * future_x
                value = max(0, trend_value) * factors[day.month - 1]
            if not np.isfinite(trend_value) or not np.isfinite(value):
                raise ValueError("Прогноз тренда выходит за поддерживаемый конечный числовой диапазон")
            values.append(value)
        values = np.asarray(values)
        training_end = (months.index[-1] + pd.offsets.MonthEnd(0)).date().isoformat()
    values = _finite("Дневной прогноз", values)
    if (values < 0).any():
        raise ValueError("Прогноз не может быть отрицательным")
    if growth is not None and not growth.empty:
        growth_rates = _finite("План роста", growth["extra_growth_rate"].to_numpy(dtype=float))
        if (growth_rates < -1).any():
            raise ValueError("План роста ниже −100% недопустим")
        for i, day in enumerate(dates):
            active = growth.loc[(growth["start_date"] <= day) & (growth["end_date"] >= day)]
            # At most one applicable plan per day; conflicting plans are explicit.
            if len(active) > 1:
                raise ValueError("Пересекаются планы роста для одной позиции")
            if len(active) == 1:
                factor = 1 + float(active.iloc[0]["extra_growth_rate"])
                with np.errstate(over="ignore", invalid="ignore"):
                    values[i] *= factor
                if not np.isfinite(values[i]):
                    raise ValueError("Прогноз после плана роста выходит за поддерживаемый конечный числовой диапазон")
    values = _finite("Итоговый дневной прогноз", values)
    with np.errstate(over="ignore", invalid="ignore"):
        horizon_total = float(np.sum(values, dtype=float))
    if not np.isfinite(horizon_total):
        raise ValueError("Сумма прогноза за горизонт выходит за поддерживаемый конечный числовой диапазон")
    return ForecastResult(pd.Series(values, index=dates, name="forecast"),
                          {m + 1: float(v) for m, v in enumerate(factors)}, seasonal_source,
                          float(slope), training_end, warnings)
