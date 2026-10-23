from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app import analysis as an
from app.market import MarketCalendar

from .conftest import frame

FORECASTS = frame(
    [
        ("2026-01-10T07:30Z", "2026-01-11T12:00Z", 1000.0),
        ("2026-01-10T09:30Z", "2026-01-11T12:00Z", 1100.0),
        ("2026-01-10T11:30Z", "2026-01-11T12:00Z", 1200.0),
        ("2026-01-10T09:30Z", "2026-01-11T13:00Z", 1300.0),
    ],
    ["publish_time", "start_time", "generation"],
)


def targets(*rows):
    return frame(list(rows), ["start_time", "cutoff"])


def test_picks_latest_forecast_published_before_cutoff():
    out = an.select_latest_forecasts(FORECASTS, targets(("2026-01-11T12:00Z", "2026-01-10T09:50Z")))
    assert out.loc[0, "forecast"] == 1100.0  # 11:30 publish is after the cutoff
    assert out.loc[0, "publish_time"] == pd.Timestamp("2026-01-10T09:30Z")
    assert out.loc[0, "horizon_h"] == pytest.approx(26.5)


def test_forecast_published_exactly_at_cutoff_is_available():
    out = an.select_latest_forecasts(FORECASTS, targets(("2026-01-11T12:00Z", "2026-01-10T11:30Z")))
    assert out.loc[0, "forecast"] == 1200.0


def test_no_eligible_forecast_gives_nan():
    out = an.select_latest_forecasts(FORECASTS, targets(("2026-01-11T12:00Z", "2026-01-10T07:00Z")))
    assert np.isnan(out.loc[0, "forecast"])


def test_selection_is_per_target_time():
    out = an.select_latest_forecasts(
        FORECASTS,
        targets(("2026-01-11T12:00Z", "2026-01-10T23:00Z"), ("2026-01-11T13:00Z", "2026-01-10T23:00Z")),
    )
    assert list(out["forecast"]) == [1200.0, 1300.0]


def test_horizon_targets_cutoff():
    t = an.horizon_targets(datetime(2026, 1, 11, 0, 15, tzinfo=UTC), datetime(2026, 1, 11, 3, tzinfo=UTC), 4)
    assert list(t["start_time"].dt.hour) == [1, 2]  # starts at the next whole hour, end exclusive
    assert (t["start_time"] - t["cutoff"] == pd.Timedelta(hours=4)).all()


def test_error_metrics_known_values():
    m = an.error_metrics(pd.Series([110.0, 90.0, 100.0, np.nan]), pd.Series([100.0, 100.0, 100.0, 100.0]))
    assert m["n"] == 3
    assert m["mae"] == pytest.approx(6.7, abs=0.05)
    assert m["bias"] == 0.0
    assert m["rmse"] == pytest.approx(np.sqrt(200 / 3), abs=0.05)
    assert m["max_over"] == 10.0 and m["max_under"] == -10.0
    assert m["wape_pct"] == pytest.approx(20 / 300 * 100, abs=0.01)


def test_error_metrics_empty():
    assert an.error_metrics(pd.Series([], dtype=float), pd.Series([], dtype=float)) == {"n": 0}


def test_band_uses_only_outcomes_known_at_decision_time():
    decision = pd.Timestamp("2026-01-10T09:50Z")
    pairs = frame(
        [
            ("2026-01-08T09:30Z", "2026-01-09T12:00Z", 1100.0, 1000.0),  # known -> residual -100
            ("2026-01-08T09:30Z", "2026-01-10T09:30Z", 1100.0, 1000.0),  # ends 10:00, after decision
        ],
        ["publish_time", "start_time", "forecast", "actual"],
    )
    pairs["error"] = pairs["forecast"] - pairs["actual"]
    pairs["horizon_h"] = (pairs["start_time"] - pairs["publish_time"]) / pd.Timedelta(hours=1)
    q, n = an.residual_quantiles(pairs, decision, np.array([26.5, 48.0]), pd.Timedelta(days=3), min_samples=1)
    assert n[0] == 1 and list(q[0]) == [-100.0, -100.0, -100.0]
    assert n[1] == 0 and np.isnan(q[1]).all()  # the other pair's outcome was not yet known


def test_band_respects_min_samples():
    pairs = frame(
        [("2026-01-08T09:30Z", "2026-01-09T12:00Z", 1100.0, 1000.0)],
        ["publish_time", "start_time", "forecast", "actual"],
    )
    pairs["error"] = 100.0
    pairs["horizon_h"] = 26.5
    q, n = an.residual_quantiles(pairs, pd.Timestamp("2026-01-10T09:50Z"), np.array([26.5]), pd.Timedelta(days=3))
    assert n[0] == 1 and np.isnan(q[0]).all()


def test_adjustment_removes_a_constant_bias():
    decision = pd.Timestamp("2026-01-10T09:50Z")
    history = pd.date_range("2026-01-08T00:00Z", "2026-01-09T23:00Z", freq="h")
    pairs = pd.DataFrame({"start_time": history, "publish_time": history - pd.Timedelta(hours=24)})
    pairs["forecast"], pairs["actual"] = 1500.0, 1000.0  # always 500 MW too high
    pairs["error"] = 500.0
    pairs["horizon_h"] = 24.0
    ev = pd.DataFrame({"forecast": [2000.0], "actual": [1500.0], "horizon_h": [24.0]})
    out, _ = an.with_adjustment(ev, pairs, decision, pd.Timedelta(days=3))
    assert out.loc[0, "adjusted"] == 1500.0
    assert an.band_coverage_pct(out) == 100.0


def test_daily_breakdown_energy():
    cal = MarketCalendar(23)
    hours = an.delivery_hours(cal, [pd.Timestamp("2026-01-15").date()])
    assert len(hours) == 24
    ev = hours.assign(forecast=1000.0, actual=900.0)
    ev["error"] = ev["forecast"] - ev["actual"]
    actuals = pd.DataFrame(
        {
            "start_time": pd.date_range("2026-01-14T23:00Z", "2026-01-15T23:00Z", freq="30min", inclusive="left"),
            "generation": 900.0,
        }
    )
    (row,) = an.daily_breakdown(ev, actuals, cal)
    assert row["forecast_energy_mwh"] == 24_000
    assert row["actual_energy_mwh"] == 21_600
    assert row["energy_error_mwh"] == 2_400
    assert row["bias"] == 100.0


def test_histogram_counts_every_error():
    errors = pd.Series([-600.0, -10.0, 10.0, 499.0, 1200.0])
    bins = an.error_histogram(errors, bin_width=500)
    assert sum(b["count"] for b in bins) == 5
    assert bins[0]["lo"] == -1000.0 and bins[-1]["hi"] == 1500.0
