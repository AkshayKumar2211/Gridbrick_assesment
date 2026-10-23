"""Builds API payloads from the loaded dataset.

Every public method is a pure function of its arguments over immutable data, so
results are memoised for the life of the process.
"""

from datetime import date, datetime, time, timedelta
from functools import lru_cache

import pandas as pd

from . import analysis as an
from .analysis import round_or_none
from .config import Settings
from .dataset import Dataset
from .market import DECISION_PRESETS, UK_TZ, MarketCalendar

BAND_HORIZON_WINDOW_H = 3.0
EARLIER_VINTAGES = 3


def iso(ts) -> str | None:
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def half_hour_grid(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame(
        {"start_time": pd.date_range(start.ceil("30min"), end, freq="30min", inclusive="left").astype(an.UTC_NS)}
    )


class AnalysisService:
    def __init__(self, dataset: Dataset, settings: Settings):
        self.ds = dataset
        self.settings = settings
        self.calendar = MarketCalendar(settings.delivery_day_start_hour)
        w = dataset.windows
        self.delivery_dates = [
            w.delivery_from + timedelta(days=i) for i in range((w.delivery_to - w.delivery_from).days + 1)
        ]
        self.scope_start = pd.Timestamp(self.calendar.delivery_window(w.delivery_from)[0])
        self.scope_end = pd.Timestamp(self.calendar.delivery_window(w.delivery_to)[1])
        self._hours = an.delivery_hours(self.calendar, self.delivery_dates)
        t = dataset.actuals["start_time"]
        self._scope_actuals = dataset.actuals[(t >= self.scope_start) & (t < self.scope_end)]
        self._lookback = pd.Timedelta(days=settings.error_lookback_days)

        self.day_ahead = lru_cache(maxsize=1024)(self._day_ahead)
        self.accuracy = lru_cache(maxsize=256)(self._accuracy)
        self.horizon_profile = lru_cache(maxsize=1)(self._horizon_profile)
        self.decision_time_profile = lru_cache(maxsize=1)(self._decision_time_profile)

    def warm_up(self) -> None:
        self.accuracy("day_ahead", self.settings.default_decision_time, None)
        self.horizon_profile()
        self.decision_time_profile()

    # --- Metadata -------------------------------------------------------------

    def meta(self) -> dict:
        s, ds = self.settings, self.ds
        publishes = ds.forecasts["publish_time"].drop_duplicates()
        slot_counts = publishes.dt.tz_convert(UK_TZ).dt.strftime("%H:%M").value_counts()
        return {
            "source": ds.source,
            "loaded_at": iso(ds.loaded_at),
            "timezone": "Europe/London",
            "decision_dates": {"from": s.decision_date_from.isoformat(), "to": s.decision_date_to.isoformat()},
            "delivery_dates": {
                "from": self.delivery_dates[0].isoformat(),
                "to": self.delivery_dates[-1].isoformat(),
            },
            "scope": {"start": iso(self.scope_start), "end": iso(self.scope_end)},
            "delivery_day_start_hour": s.delivery_day_start_hour,
            "default_decision_time": s.default_decision_time.strftime("%H:%M"),
            "decision_time_presets": DECISION_PRESETS,
            "max_horizon_hours": s.max_horizon_hours,
            "error_lookback_days": s.error_lookback_days,
            # Regular slots only (ignore one-off re-publishes).
            "publish_schedule": sorted(slot_counts[slot_counts >= 3].index.tolist()),
            "actuals": {
                "count": len(ds.actuals),
                "first": iso(ds.actuals["start_time"].min()),
                "last": iso(ds.actuals["start_time"].max()),
            },
            "forecasts": {
                "count": len(ds.forecasts),
                "publishes": int(publishes.size),
                "first_publish": iso(publishes.min()),
                "last_publish": iso(publishes.max()),
            },
        }

    # --- Day-ahead desk -------------------------------------------------------

    def _day_ahead(self, delivery_date: date, decision_time: time) -> dict:
        cal = self.calendar
        start, end = (pd.Timestamp(x) for x in cal.delivery_window(delivery_date))
        decision_at = pd.Timestamp(cal.decision_at(delivery_date, decision_time))

        hours = self._hours[self._hours["delivery_date"] == delivery_date]
        selected = an.select_latest_forecasts(self.ds.forecasts, an.with_day_ahead_cutoff(hours, cal, decision_time))
        ev, samples = an.with_adjustment(
            an.attach_actuals(selected, self.ds.actuals),
            self.ds.pairs,
            decision_at,
            self._lookback,
            BAND_HORIZON_WINDOW_H,
        )

        t = self.ds.actuals["start_time"]
        actual_hh = self.ds.actuals[(t >= start) & (t < end)]
        grid = (
            half_hour_grid(start, end)
            .merge(actual_hh.rename(columns={"generation": "actual"}), on="start_time", how="left")
            .merge(ev[["start_time", "forecast", "adjusted", "band_low", "band_high"]], on="start_time", how="left")
        )
        points = [
            {
                "time": iso(r.start_time),
                "actual": round_or_none(r.actual),
                "forecast": round_or_none(r.forecast),
                "adjusted": round_or_none(r.adjusted),
                "band_low": round_or_none(r.band_low),
                "band_high": round_or_none(r.band_high),
            }
            for r in grid.itertuples(index=False)
        ]

        latest = selected["publish_time"].max()
        forecast_energy = an.energy_mwh(ev["forecast"], 1.0)
        actual_energy = an.energy_mwh(actual_hh["generation"], 0.5)
        return {
            "delivery_date": delivery_date.isoformat(),
            "decision_time": decision_time.strftime("%H:%M"),
            "decision_at": iso(decision_at),
            "window": {"start": iso(start), "end": iso(end)},
            "forecast_publish_time": iso(latest),
            "forecast_age_minutes": None if pd.isna(latest) else int((decision_at - latest) / pd.Timedelta(minutes=1)),
            "horizon_range_h": [round_or_none(ev["horizon_h"].min()), round_or_none(ev["horizon_h"].max())],
            "band": {
                "quantiles": list(an.BAND_QUANTILES),
                "lookback_days": self.settings.error_lookback_days,
                "horizon_window_h": BAND_HORIZON_WINDOW_H,
                "min_samples": int(samples.min()) if len(samples) else 0,
            },
            "summary": {
                "forecast_energy_mwh": forecast_energy,
                "adjusted_energy_mwh": an.energy_mwh(ev["adjusted"], 1.0),
                "low_case_energy_mwh": an.energy_mwh(ev["band_low"], 1.0),
                "high_case_energy_mwh": an.energy_mwh(ev["band_high"], 1.0),
                "actual_energy_mwh": actual_energy,
                "energy_error_mwh": round_or_none(forecast_energy - actual_energy, 0)
                if forecast_energy is not None and actual_energy is not None
                else None,
                "actual_complete": len(actual_hh) == len(grid),
                "band_coverage_pct": an.band_coverage_pct(ev),
                "metrics": an.error_metrics(ev["forecast"], ev["actual"]),
                "adjusted_metrics": an.error_metrics(ev["adjusted"], ev["actual"]),
            },
            "points": points,
            "earlier_forecasts": self._earlier_vintages(latest, start, end),
        }

    def _earlier_vintages(self, latest: pd.Timestamp, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
        """The publishes just before the one used - shows how the forecast moved."""
        if pd.isna(latest):
            return []
        f = self.ds.forecasts
        previous = f.loc[f["publish_time"] < latest, "publish_time"].drop_duplicates().nlargest(EARLIER_VINTAGES)
        in_window = f[(f["start_time"] >= start) & (f["start_time"] < end)]
        return [
            {
                "publish_time": iso(p),
                "points": [
                    {"time": iso(r.start_time), "forecast": round_or_none(r.generation)}
                    for r in in_window[in_window["publish_time"] == p].itertuples(index=False)
                ],
            }
            for p in previous
        ]

    # --- Explorer -------------------------------------------------------------

    def explorer(self, start: datetime, end: datetime, horizon_h: float) -> dict:
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        selected = an.select_latest_forecasts(self.ds.forecasts, an.horizon_targets(start, end, horizon_h))
        ev = an.attach_actuals(selected, self.ds.actuals)
        t = self.ds.actuals["start_time"]
        grid = (
            half_hour_grid(start, end)
            .merge(
                self.ds.actuals[(t >= start) & (t < end)].rename(columns={"generation": "actual"}),
                on="start_time",
                how="left",
            )
            .merge(ev[["start_time", "forecast", "publish_time", "horizon_h"]], on="start_time", how="left")
        )
        return {
            "start": iso(start),
            "end": iso(end),
            "horizon_hours": horizon_h,
            "metrics": an.error_metrics(ev["forecast"], ev["actual"]),
            "points": [
                {
                    "time": iso(r.start_time),
                    "actual": round_or_none(r.actual),
                    "forecast": round_or_none(r.forecast),
                    "publish_time": iso(r.publish_time),
                    "horizon_h": round_or_none(r.horizon_h),
                }
                for r in grid.itertuples(index=False)
            ],
        }

    # --- Accuracy -------------------------------------------------------------

    def _accuracy(self, mode: str, decision_time: time | None, horizon_h: float | None) -> dict:
        if mode == "day_ahead":
            targets = an.with_day_ahead_cutoff(self._hours, self.calendar, decision_time)
            label = f"Latest forecast published by {decision_time:%H:%M} UK time on the day before delivery"
        else:
            targets = an.horizon_targets(self.scope_start, self.scope_end, horizon_h)
            targets["delivery_date"] = self.calendar.delivery_dates_of(targets["start_time"])
            label = f"Latest forecast published at least {horizon_h:g} h before each hour"
        selected = an.select_latest_forecasts(self.ds.forecasts, targets)
        ev = an.attach_actuals(selected, self.ds.actuals)
        adjusted_metrics = coverage = None
        if mode == "day_ahead":
            # Each day is adjusted with only the errors known at its own decision time.
            ev = pd.concat(
                [
                    an.with_adjustment(
                        g,
                        self.ds.pairs,
                        self.calendar.decision_at(day, decision_time),
                        self._lookback,
                        BAND_HORIZON_WINDOW_H,
                    )[0]
                    for day, g in ev.groupby("delivery_date", sort=True)
                ],
                ignore_index=True,
            )
            adjusted_metrics = an.error_metrics(ev["adjusted"], ev["actual"])
            coverage = an.band_coverage_pct(ev)
        matched = ev.dropna(subset=["forecast", "actual"])
        return {
            "selection": {
                "mode": mode,
                "decision_time": decision_time.strftime("%H:%M") if decision_time else None,
                "horizon_hours": horizon_h,
                "label": label,
                "mean_horizon_h": round_or_none(selected["horizon_h"].mean()),
            },
            "metrics": an.error_metrics(ev["forecast"], ev["actual"]),
            "adjusted_metrics": adjusted_metrics,
            "band_coverage_pct": coverage,
            "signed_error_quantiles": an.signed_error_quantiles(ev["error"]),
            "daily": an.daily_breakdown(ev, self._scope_actuals, self.calendar),
            "by_hour": an.hour_of_day_breakdown(ev),
            "histogram": an.error_histogram(ev["error"]),
            "scatter": [
                {"time": iso(r.start_time), "forecast": round_or_none(r.forecast), "actual": round_or_none(r.actual)}
                for r in matched.itertuples(index=False)
            ],
        }

    def _horizon_profile(self) -> list[dict]:
        return an.horizon_profile(self.ds.pairs, self.scope_start, self.scope_end, self.settings.max_horizon_hours)

    def _decision_time_profile(self) -> list[dict]:
        # A decision must precede the start of its delivery day (23:00 on D-1).
        last_minute = (self.settings.delivery_day_start_hour or 24) * 60
        return an.decision_time_profile(
            self.ds.forecasts, self.ds.actuals, self.calendar, self.delivery_dates, last_minute=last_minute
        )
