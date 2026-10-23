"""Synthetic, deterministic Elexon-shaped data so tests never touch the network.

Actual wind follows a smooth curve; every forecast equals the actual plus an
over-forecast of BIAS_PER_HOUR MW per hour of lead time. That makes "which
forecast was picked" directly observable from its error.
"""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dataset import build_dataset, data_windows
from app.main import create_app
from app.market import MarketCalendar
from app.store import DataStore

PUBLISH_SLOTS = ["02:30", "04:30", "07:30", "09:30", "11:30", "15:30", "18:30", "22:30"]
BIAS_PER_HOUR = 10.0


def actual_mw(ts: datetime) -> float:
    hours = ts.timestamp() / 3600
    return round(9000 + 3000 * np.sin(hours / 7), 1)


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_records(windows) -> tuple[list[dict], list[dict]]:
    actuals = []
    t = windows.actuals_from
    while t < windows.actuals_to:
        actuals.append(
            {
                "publishTime": _iso(t + timedelta(minutes=30)),
                "startTime": _iso(t),
                "fuelType": "WIND",
                "generation": actual_mw(t),
            }
        )
        t += timedelta(minutes=30)

    forecasts = []
    day = windows.publish_from.date()
    while day <= windows.publish_to.date():
        for slot in PUBLISH_SLOTS:
            hh, mm = map(int, slot.split(":"))
            published = datetime(day.year, day.month, day.day, hh, mm, tzinfo=UTC)
            if not windows.publish_from <= published < windows.publish_to:
                continue
            first = published.replace(minute=0) - timedelta(hours=24)  # WINDFOR also repeats past hours
            for k in range(73):
                target = first + timedelta(hours=k)
                horizon = (target - published) / timedelta(hours=1)
                forecasts.append(
                    {
                        "publishTime": _iso(published),
                        "startTime": _iso(target),
                        "generation": round(actual_mw(target) + BIAS_PER_HOUR * max(horizon, 0), 1),
                    }
                )
        day += timedelta(days=1)
    return actuals, forecasts


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        decision_date_from=date(2026, 1, 1),
        decision_date_to=date(2026, 1, 5),
        error_lookback_days=3,
        data_source="snapshot",
        cors_origins="*",
    )


@pytest.fixture(scope="session")
def dataset(settings):
    windows = data_windows(settings, MarketCalendar(settings.delivery_day_start_hour))
    actuals, forecasts = make_records(windows)
    return build_dataset(actuals, forecasts, windows, source="test")


@pytest.fixture(scope="session")
def client(settings, dataset):
    app = create_app(settings, store=DataStore.from_dataset(dataset, settings))
    with TestClient(app) as c:
        yield c


def frame(rows: list[tuple], columns: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    for col in columns:
        if col.endswith("_time") or col == "cutoff":
            df[col] = pd.to_datetime(df[col], utc=True)
    return df
