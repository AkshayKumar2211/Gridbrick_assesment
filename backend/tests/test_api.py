import asyncio

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import DataStore

from .conftest import BIAS_PER_HOUR


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "data": "ready", "error": None}


def test_meta_describes_scope(client):
    meta = client.get("/api/meta").json()
    assert meta["delivery_dates"] == {"from": "2026-01-02", "to": "2026-01-06"}
    assert meta["default_decision_time"] == "09:50"
    assert meta["publish_schedule"] == ["02:30", "04:30", "07:30", "09:30", "11:30", "15:30", "18:30", "22:30"]
    # No forecast published after the last decision day is ever loaded.
    assert meta["forecasts"]["last_publish"] <= "2026-01-06T00:00:00Z"


def test_day_ahead_uses_latest_forecast_before_decision(client):
    body = client.get("/api/day-ahead", params={"delivery_date": "2026-01-03", "decision_time": "09:50"}).json()
    assert body["decision_at"] == "2026-01-02T09:50:00Z"
    assert body["forecast_publish_time"] == "2026-01-02T09:30:00Z"
    assert body["forecast_age_minutes"] == 20
    assert body["window"] == {"start": "2026-01-02T23:00:00Z", "end": "2026-01-03T23:00:00Z"}
    assert len(body["points"]) == 48  # half-hourly grid
    hourly = [p for p in body["points"] if p["forecast"] is not None]
    assert len(hourly) == 24
    # Synthetic forecasts over-forecast by BIAS_PER_HOUR per hour of lead time.
    first = hourly[0]
    assert first["forecast"] - first["actual"] == pytest.approx(BIAS_PER_HOUR * 13.5, abs=0.2)
    assert body["summary"]["metrics"]["bias"] > 0
    assert len(body["earlier_forecasts"]) == 3
    assert body["earlier_forecasts"][0]["publish_time"] == "2026-01-02T07:30:00Z"


def test_earlier_decision_uses_older_forecast(client):
    body = client.get("/api/day-ahead", params={"delivery_date": "2026-01-03", "decision_time": "09:20"}).json()
    assert body["forecast_publish_time"] == "2026-01-02T07:30:00Z"


def test_band_is_present_and_ordered(client):
    body = client.get("/api/day-ahead", params={"delivery_date": "2026-01-05"}).json()
    banded = [p for p in body["points"] if p["band_low"] is not None]
    assert banded, "expected an uncertainty band once enough history exists"
    assert all(p["band_low"] <= p["band_high"] for p in banded)
    assert body["summary"]["low_case_energy_mwh"] <= body["summary"]["high_case_energy_mwh"]


@pytest.mark.parametrize(
    "params",
    [
        {"delivery_date": "2026-01-01"},  # decided in December - out of scope
        {"delivery_date": "2026-01-07"},
        {"delivery_date": "2026-01-03", "decision_time": "23:30"},  # after delivery starts
        {"delivery_date": "not-a-date"},
    ],
)
def test_day_ahead_validation(client, params):
    assert client.get("/api/day-ahead", params=params).status_code == 422


def test_accuracy_day_ahead(client):
    body = client.get("/api/accuracy", params={"mode": "day_ahead", "decision_time": "09:50"}).json()
    assert body["metrics"]["n"] == 5 * 24
    assert len(body["daily"]) == 5
    assert len(body["by_hour"]) == 24
    assert sum(b["count"] for b in body["histogram"]) == body["metrics"]["n"]
    assert body["selection"]["mode"] == "day_ahead"
    # Synthetic forecasts carry a consistent bias, so the adjustment must remove most of it.
    assert abs(body["adjusted_metrics"]["bias"]) < body["metrics"]["bias"] / 2
    assert body["band_coverage_pct"] is not None


def test_accuracy_horizon_mode_has_no_adjustment(client):
    body = client.get("/api/accuracy", params={"mode": "horizon", "horizon_hours": 12}).json()
    assert body["adjusted_metrics"] is None and body["band_coverage_pct"] is None
    assert all(row["adjusted_energy_error_mwh"] is None for row in body["daily"])


def test_shorter_horizon_is_more_accurate(client):
    short = client.get("/api/accuracy", params={"mode": "horizon", "horizon_hours": 2}).json()
    long = client.get("/api/accuracy", params={"mode": "horizon", "horizon_hours": 36}).json()
    assert short["metrics"]["mae"] < long["metrics"]["mae"]


def test_horizon_profile_grows_with_lead_time(client):
    rows = client.get("/api/accuracy/horizon-profile").json()
    maes = [r["mae"] for r in rows]
    assert rows[0]["horizon_h"] == 0 and rows[-1]["horizon_h"] == 47
    assert maes == sorted(maes)


def test_decision_time_profile_stops_before_delivery_starts(client):
    rows = client.get("/api/accuracy/decision-time-profile").json()
    assert rows[0]["decision_time"] == "00:00" and rows[-1]["decision_time"] == "22:30"
    by_time = {r["decision_time"]: r for r in rows}
    assert by_time["09:30"]["typical_publish_time"] == "09:30"
    # Waiting past the 09:30 publish buys a fresher forecast.
    assert by_time["10:00"]["mae"] < by_time["09:00"]["mae"]


def test_explorer(client):
    body = client.get(
        "/api/explorer", params={"start": "2026-01-03T00:00", "end": "2026-01-04T00:00", "horizon_hours": 6}
    ).json()
    assert len(body["points"]) == 48
    horizons = [p["horizon_h"] for p in body["points"] if p["horizon_h"] is not None]
    assert min(horizons) >= 6


@pytest.mark.parametrize(
    "params",
    [
        {"start": "2026-01-04T00:00", "end": "2026-01-03T00:00"},
        {"start": "2025-12-01T00:00", "end": "2026-01-03T00:00"},
        {"start": "2026-01-03T00:00", "end": "2026-01-04T00:00", "horizon_hours": 72},
    ],
)
def test_explorer_validation(client, params):
    assert client.get("/api/explorer", params=params).status_code == 422


def test_returns_503_while_data_is_loading(settings):
    async def never_finishes():
        await asyncio.sleep(3600)

    slow = settings.model_copy(update={"data_wait_timeout_s": 0.05})
    app = create_app(slow, store=DataStore(slow, loader=never_finishes))
    with TestClient(app) as c:
        response = c.get("/api/meta")
        assert response.status_code == 503
        assert response.headers["retry-after"] == "5"
        assert c.get("/api/health").json()["data"] == "loading"


def test_iso_timestamps_are_utc(client):
    body = client.get("/api/day-ahead", params={"delivery_date": "2026-01-03"}).json()
    assert all(pd.Timestamp(p["time"]).tzname() == "UTC" for p in body["points"])
