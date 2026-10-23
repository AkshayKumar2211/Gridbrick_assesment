"""Which data is in scope, and how it is loaded (live from Elexon or from the snapshot)."""

import asyncio
import gzip
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from .analysis import forecast_actual_pairs
from .config import Settings
from .elexon import ElexonClient, parse_actuals, parse_forecasts
from .market import UK_TZ, MarketCalendar, to_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataWindows:
    delivery_from: date  # first in-scope delivery day
    delivery_to: date  # last in-scope delivery day
    actuals_from: datetime  # UTC, inclusive
    actuals_to: datetime  # UTC, exclusive
    publish_from: datetime  # UTC, inclusive
    publish_to: datetime  # UTC, exclusive


def data_windows(settings: Settings, calendar: MarketCalendar) -> DataWindows:
    """Derive exactly which data the in-scope decisions need.

    * Delivery days: one day after each decision date.
    * Forecasts: anything that could be "the latest available" at a decision, i.e.
      published before the end of the last decision date. Nothing later is used.
    * History: the uncertainty band at the first decision looks back
      `error_lookback_days`, so actuals start that far before it, and forecasts a
      further `max_horizon_hours` earlier.
    """
    delivery_from = settings.decision_date_from + timedelta(days=1)
    delivery_to = settings.decision_date_to + timedelta(days=1)
    history_start = to_utc(datetime.combine(settings.decision_date_from, time(0))) - timedelta(
        days=settings.error_lookback_days
    )
    return DataWindows(
        delivery_from=delivery_from,
        delivery_to=delivery_to,
        actuals_from=history_start,
        actuals_to=calendar.delivery_window(delivery_to)[1],
        publish_from=history_start - timedelta(hours=settings.max_horizon_hours),
        publish_to=to_utc(datetime.combine(settings.decision_date_to + timedelta(days=1), time(0))),
    )


@dataclass(frozen=True)
class Dataset:
    actuals: pd.DataFrame  # start_time, generation
    forecasts: pd.DataFrame  # publish_time, start_time, generation, horizon_h
    pairs: pd.DataFrame  # every forecast joined to its actual, with error
    windows: DataWindows
    source: str
    loaded_at: datetime


def build_dataset(
    actual_records: list[dict], forecast_records: list[dict], windows: DataWindows, source: str
) -> Dataset:
    actuals = parse_actuals(actual_records)
    actuals = actuals[(actuals["start_time"] >= windows.actuals_from) & (actuals["start_time"] < windows.actuals_to)]
    forecasts = parse_forecasts(forecast_records)
    forecasts = forecasts[
        (forecasts["publish_time"] >= windows.publish_from) & (forecasts["publish_time"] < windows.publish_to)
    ]
    actuals = actuals.reset_index(drop=True)
    forecasts = forecasts.reset_index(drop=True)
    return Dataset(
        actuals=actuals,
        forecasts=forecasts,
        pairs=forecast_actual_pairs(forecasts, actuals),
        windows=windows,
        source=source,
        loaded_at=datetime.now(UTC),
    )


async def fetch_live(settings: Settings, windows: DataWindows) -> tuple[list[dict], list[dict]]:
    client = ElexonClient(
        settings.elexon_base_url,
        timeout_s=settings.request_timeout_s,
        retries=settings.request_retries,
        chunk_days=settings.fetch_chunk_days,
    )
    # FUELHH is keyed by settlement date, which is a UK local date.
    settlement_from = windows.actuals_from.astimezone(UK_TZ).date()
    settlement_to = (windows.actuals_to - timedelta(seconds=1)).astimezone(UK_TZ).date()
    actuals, forecasts = await asyncio.gather(
        client.fetch_actuals(settlement_from, settlement_to),
        client.fetch_forecasts(windows.publish_from, windows.publish_to),
    )
    return actuals, forecasts


def read_snapshot(path: Path) -> tuple[list[dict], list[dict]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload["actuals"], payload["forecasts"]


def write_snapshot(path: Path, actuals: list[dict], forecasts: list[dict]) -> None:
    keep_actual = ("publishTime", "startTime", "fuelType", "generation")
    keep_forecast = ("publishTime", "startTime", "generation")
    payload = {
        "source": "Elexon BMRS (FUELHH, WINDFOR)",
        "generated_at": datetime.now(UTC).isoformat(),
        "actuals": [{k: r.get(k) for k in keep_actual} for r in actuals],
        "forecasts": [{k: r.get(k) for k in keep_forecast} for r in forecasts],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))


async def load_dataset(settings: Settings) -> Dataset:
    windows = data_windows(settings, MarketCalendar(settings.delivery_day_start_hour))
    if settings.data_source != "snapshot":
        try:
            actuals, forecasts = await fetch_live(settings, windows)
            logger.info("Fetched %d actual and %d forecast rows from Elexon", len(actuals), len(forecasts))
            return build_dataset(actuals, forecasts, windows, source="elexon-live")
        except Exception:
            if settings.data_source == "live":
                raise
            logger.exception("Live Elexon fetch failed; falling back to bundled snapshot")
    actuals, forecasts = read_snapshot(settings.snapshot_path)
    return build_dataset(actuals, forecasts, windows, source="snapshot")
