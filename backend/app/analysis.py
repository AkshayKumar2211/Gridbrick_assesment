"""Forecast selection and error analysis.

Pure functions over pandas frames - no I/O, no global state - so every rule the
product relies on is unit-testable in isolation.

Conventions
-----------
* All timestamps are tz-aware UTC.
* error = forecast - actual (MW). Positive error = over-forecast = less wind than
  planned for, i.e. the desk is left short and must buy the gap later.
* Forecasts (WINDFOR) are hourly; actuals (FUELHH) are half-hourly. MW error metrics
  compare them at matching on-the-hour timestamps; energy (MWh) integrates each
  series at its own resolution.
"""

from collections.abc import Iterable
from datetime import date, datetime, time

import numpy as np
import pandas as pd

from .market import UK_TZ, MarketCalendar

HOUR = pd.Timedelta(hours=1)
HALF_HOUR = pd.Timedelta(minutes=30)
UTC_NS = "datetime64[ns, UTC]"


# --- Target construction ------------------------------------------------------


def hourly_times(start: datetime, end: datetime) -> pd.DatetimeIndex:
    """On-the-hour timestamps in [start, end)."""
    first = pd.Timestamp(start).tz_convert("UTC").ceil("h")
    return pd.date_range(first, pd.Timestamp(end).tz_convert("UTC"), freq="h", inclusive="left").astype(UTC_NS)


def delivery_hours(calendar: MarketCalendar, delivery_dates: Iterable[date]) -> pd.DataFrame:
    """One row per hourly forecast target in each delivery day: (start_time, delivery_date)."""
    frames = [
        pd.DataFrame({"start_time": hourly_times(*calendar.delivery_window(d)), "delivery_date": d})
        for d in delivery_dates
    ]
    return pd.concat(frames, ignore_index=True)


def with_day_ahead_cutoff(hours: pd.DataFrame, calendar: MarketCalendar, decision_time: time) -> pd.DataFrame:
    """Add `cutoff` = decision instant on D-1 for each row's delivery day."""
    cutoffs = {d: pd.Timestamp(calendar.decision_at(d, decision_time)) for d in hours["delivery_date"].unique()}
    return hours.assign(cutoff=hours["delivery_date"].map(cutoffs).astype(UTC_NS))


def horizon_targets(start: datetime, end: datetime, horizon_h: float) -> pd.DataFrame:
    """Hourly targets in [start, end) whose cutoff is `horizon_h` hours before the target."""
    times = hourly_times(start, end)
    return pd.DataFrame({"start_time": times, "cutoff": times - pd.Timedelta(hours=horizon_h)})


# --- Selection ----------------------------------------------------------------


def select_latest_forecasts(forecasts: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """For each target (start_time, cutoff), pick the most recent forecast for that
    start_time that was published at or before `cutoff`.

    This is the core business rule: it reproduces exactly what was knowable at the
    moment of decision. Targets with no eligible forecast get NaN.
    """
    if targets.empty:
        return targets.assign(publish_time=pd.Series(dtype=UTC_NS), forecast=np.nan, horizon_h=np.nan)
    right = forecasts[["publish_time", "start_time", "generation"]].sort_values("publish_time")
    merged = pd.merge_asof(
        targets.sort_values("cutoff"),
        right,
        left_on="cutoff",
        right_on="publish_time",
        by="start_time",
        direction="backward",
        allow_exact_matches=True,
    ).rename(columns={"generation": "forecast"})
    merged["horizon_h"] = (merged["start_time"] - merged["publish_time"]) / HOUR
    return merged.sort_values("start_time").reset_index(drop=True)


def attach_actuals(selected: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    """Join actual generation at the same start_time and compute error = forecast - actual."""
    out = selected.merge(actuals.rename(columns={"generation": "actual"}), on="start_time", how="left")
    out["error"] = out["forecast"] - out["actual"]
    return out


def forecast_actual_pairs(forecasts: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    """Every (publish, target) forecast that has a matching actual - the raw material
    for horizon profiles and uncertainty bands."""
    pairs = forecasts.merge(actuals.rename(columns={"generation": "actual"}), on="start_time", how="inner")
    pairs = pairs.rename(columns={"generation": "forecast"})
    pairs["error"] = pairs["forecast"] - pairs["actual"]
    return pairs


# --- Metrics ------------------------------------------------------------------


def round_or_none(x: float | None, digits: int = 1) -> float | None:
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), digits)


def error_metrics(forecast: pd.Series, actual: pd.Series) -> dict:
    """Point-forecast error metrics (MW) over rows where both values exist."""
    mask = forecast.notna() & actual.notna()
    f = forecast[mask].to_numpy(dtype=float)
    a = actual[mask].to_numpy(dtype=float)
    n = int(f.size)
    if n == 0:
        return {"n": 0}
    e = f - a
    abs_e = np.abs(e)
    corr = np.corrcoef(f, a)[0, 1] if n > 1 and f.std() > 0 and a.std() > 0 else None
    return {
        "n": n,
        "mae": round_or_none(abs_e.mean()),
        "rmse": round_or_none(np.sqrt(np.mean(e**2))),
        "bias": round_or_none(e.mean()),
        # Weighted APE: robust alternative to MAPE, which explodes on low-wind hours.
        "wape_pct": round_or_none(abs_e.sum() / a.sum() * 100, 2) if a.sum() > 0 else None,
        "p50_abs": round_or_none(np.quantile(abs_e, 0.5)),
        "p90_abs": round_or_none(np.quantile(abs_e, 0.9)),
        "p95_abs": round_or_none(np.quantile(abs_e, 0.95)),
        "max_over": round_or_none(e.max()),
        "max_under": round_or_none(e.min()),
        "correlation": round_or_none(corr, 4),
        "mean_actual": round_or_none(a.mean()),
    }


SIGNED_QUANTILES = {"p05": 0.05, "p10": 0.10, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p90": 0.90, "p95": 0.95}


def signed_error_quantiles(errors: pd.Series) -> dict:
    e = errors.dropna().to_numpy(dtype=float)
    if e.size == 0:
        return {k: None for k in SIGNED_QUANTILES}
    return {k: round_or_none(np.quantile(e, q)) for k, q in SIGNED_QUANTILES.items()}


def error_histogram(errors: pd.Series, bin_width: float = 500.0) -> list[dict]:
    e = errors.dropna().to_numpy(dtype=float)
    if e.size == 0:
        return []
    lo = np.floor(e.min() / bin_width) * bin_width
    hi = np.ceil(e.max() / bin_width) * bin_width
    edges = np.arange(lo, hi + bin_width, bin_width)
    counts, edges = np.histogram(e, bins=edges)
    return [{"lo": float(edges[i]), "hi": float(edges[i + 1]), "count": int(c)} for i, c in enumerate(counts)]


# --- Breakdowns ---------------------------------------------------------------


def energy_mwh(series: pd.Series, step_hours: float) -> float | None:
    """Energy of a MW series sampled every `step_hours` (rectangle rule)."""
    s = series.dropna()
    return round_or_none(s.sum() * step_hours, 0) if len(s) else None


def _difference(a: float | None, b: float | None) -> float | None:
    return round_or_none(a - b, 0) if a is not None and b is not None else None


def daily_breakdown(evaluated: pd.DataFrame, actuals: pd.DataFrame, calendar: MarketCalendar) -> list[dict]:
    """Per delivery day: MW error metrics and energy (MWh) forecast vs actual.
    Includes the bias-adjusted forecast's energy error when `evaluated` has one."""
    halfhours = actuals.assign(delivery_date=calendar.delivery_dates_of(actuals["start_time"]))
    actual_energy = halfhours.groupby("delivery_date")["generation"].sum() * 0.5
    has_adjusted = "adjusted" in evaluated
    rows = []
    for day, g in evaluated.groupby("delivery_date", sort=True):
        m = error_metrics(g["forecast"], g["actual"])
        fc_energy = energy_mwh(g["forecast"], 1.0)
        act_energy = round_or_none(actual_energy.get(day, np.nan), 0)
        rows.append(
            {
                "delivery_date": day.isoformat(),
                "mae": m.get("mae"),
                "bias": m.get("bias"),
                "max_abs_error": round_or_none(g["error"].abs().max()),
                "forecast_energy_mwh": fc_energy,
                "actual_energy_mwh": act_energy,
                "energy_error_mwh": _difference(fc_energy, act_energy),
                "adjusted_energy_error_mwh": _difference(energy_mwh(g["adjusted"], 1.0), act_energy)
                if has_adjusted
                else None,
            }
        )
    return rows


def hour_of_day_breakdown(evaluated: pd.DataFrame) -> list[dict]:
    """Error by UK local hour of the target."""
    df = evaluated.dropna(subset=["error"])
    hours = df["start_time"].dt.tz_convert(UK_TZ).dt.hour
    rows = []
    for hour, g in df.groupby(hours, sort=True):
        e = g["error"]
        rows.append(
            {
                "hour": int(hour),
                "n": int(len(e)),
                "mae": round_or_none(e.abs().mean()),
                "bias": round_or_none(e.mean()),
                "p10": round_or_none(e.quantile(0.1)),
                "p90": round_or_none(e.quantile(0.9)),
            }
        )
    return rows


def horizon_profile(
    pairs: pd.DataFrame, target_from: datetime, target_to: datetime, max_horizon_h: float, bin_h: float = 1.0
) -> list[dict]:
    """How error grows with lead time, using every forecast (not only the latest)."""
    df = pairs[
        (pairs["start_time"] >= target_from) & (pairs["start_time"] < target_to) & (pairs["horizon_h"] < max_horizon_h)
    ]
    buckets = (np.floor(df["horizon_h"] / bin_h) * bin_h).rename("bucket")
    rows = []
    for bucket, g in df.groupby(buckets, sort=True):
        e = g["error"]
        rows.append(
            {
                "horizon_h": float(bucket),
                "n": int(len(e)),
                "mae": round_or_none(e.abs().mean()),
                "rmse": round_or_none(np.sqrt((e**2).mean())),
                "bias": round_or_none(e.mean()),
                "p10": round_or_none(e.quantile(0.1)),
                "p90": round_or_none(e.quantile(0.9)),
            }
        )
    return rows


def decision_time_profile(
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    calendar: MarketCalendar,
    delivery_dates: list[date],
    step_minutes: int = 30,
    last_minute: int = 24 * 60,
) -> list[dict]:
    """Day-ahead accuracy as a function of the time of day the decision is taken on D-1
    (decision times from 00:00 up to, not including, `last_minute` after midnight)."""
    hours = delivery_hours(calendar, delivery_dates)
    rows = []
    for minutes in range(0, last_minute, step_minutes):
        t = time(minutes // 60, minutes % 60)
        selected = select_latest_forecasts(forecasts, with_day_ahead_cutoff(hours, calendar, t))
        evaluated = attach_actuals(selected, actuals)
        m = error_metrics(evaluated["forecast"], evaluated["actual"])
        published = selected["publish_time"].dropna().dt.tz_convert(UK_TZ).dt.strftime("%H:%M")
        rows.append(
            {
                "decision_time": t.strftime("%H:%M"),
                "mae": m.get("mae"),
                "rmse": m.get("rmse"),
                "bias": m.get("bias"),
                "n": m["n"],
                "typical_publish_time": published.mode().iat[0] if len(published) else None,
                "mean_horizon_h": round_or_none(selected["horizon_h"].mean()),
            }
        )
    return rows


# --- Uncertainty --------------------------------------------------------------


BAND_QUANTILES = (0.1, 0.5, 0.9)


def residual_quantiles(
    pairs: pd.DataFrame,
    decision_at: datetime,
    horizons: np.ndarray,
    lookback: pd.Timedelta,
    window_h: float = 3.0,
    quantiles: tuple[float, ...] = BAND_QUANTILES,
    min_samples: int = 30,
) -> tuple[np.ndarray, np.ndarray]:
    """Empirical quantiles of the residual (actual - forecast) for each target horizon.

    Uses only forecasts whose outcome was already known at `decision_at` (the
    half-hour had finished) within the trailing `lookback`, and whose horizon was
    within +/- `window_h` of the target's. No look-ahead: this is what the desk
    could have computed at the moment of decision.

    Returns (q, sample_count): q has shape (len(horizons), len(quantiles)) and is
    NaN where the sample is smaller than `min_samples`.
    """
    decision_at = pd.Timestamp(decision_at)
    known = pairs[(pairs["start_time"] + HALF_HOUR <= decision_at) & (pairs["start_time"] >= decision_at - lookback)]
    resid = -known["error"].to_numpy(dtype=float)
    known_h = known["horizon_h"].to_numpy(dtype=float)
    q = np.full((len(horizons), len(quantiles)), np.nan)
    counts = np.zeros(len(horizons), dtype=int)
    for i, h in enumerate(horizons):
        if not np.isfinite(h):
            continue
        sample = resid[np.abs(known_h - h) <= window_h]
        counts[i] = sample.size
        if sample.size >= min_samples:
            q[i] = np.quantile(sample, quantiles)
    return q, counts


def with_adjustment(
    evaluated: pd.DataFrame, pairs: pd.DataFrame, decision_at: datetime, lookback: pd.Timedelta, window_h: float = 3.0
) -> tuple[pd.DataFrame, np.ndarray]:
    """Add the bias-adjusted forecast and its uncertainty band.

    adjusted  = forecast + median recent residual  (removes systematic bias)
    band_low  = forecast + 10th percentile residual (low-wind case)
    band_high = forecast + 90th percentile residual (high-wind case)
    """
    q, counts = residual_quantiles(
        pairs, decision_at, evaluated["horizon_h"].to_numpy(dtype=float), lookback, window_h, BAND_QUANTILES
    )
    f = evaluated["forecast"].to_numpy(dtype=float)
    out = evaluated.assign(
        band_low=np.clip(f + q[:, 0], 0, None),
        adjusted=np.clip(f + q[:, 1], 0, None),
        band_high=np.clip(f + q[:, 2], 0, None),
    )
    return out, counts


def band_coverage_pct(df: pd.DataFrame) -> float | None:
    """Share of hours whose actual fell inside [band_low, band_high] (target: ~80%)."""
    banded = df.dropna(subset=["actual", "band_low", "band_high"])
    if banded.empty:
        return None
    inside = (banded["actual"] >= banded["band_low"]) & (banded["actual"] <= banded["band_high"])
    return round_or_none(inside.mean() * 100)
