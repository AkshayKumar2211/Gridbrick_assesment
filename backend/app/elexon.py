"""Elexon BMRS client and record parsing.

Datasets used (national level, wind only):
  FUELHH  - half-hourly outturn generation by fuel type (actuals), filtered to fuelType=WIND
  WINDFOR - hourly wind generation forecasts, re-published ~8 times a day
"""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

ACTUAL_COLUMNS = ["start_time", "generation"]
FORECAST_COLUMNS = ["publish_time", "start_time", "generation", "horizon_h"]


class ElexonClient:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = 30.0,
        retries: int = 3,
        chunk_days: int = 14,
        backoff_s: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._retries = retries
        self._chunk = timedelta(days=chunk_days)
        self._backoff = backoff_s
        self._transport = transport  # injectable for tests

    async def fetch_actuals(self, settlement_from: date, settlement_to: date) -> list[dict]:
        """WIND outturn for settlement dates in [settlement_from, settlement_to] (inclusive)."""
        chunks = []
        cursor = settlement_from
        while cursor <= settlement_to:
            end = min(cursor + self._chunk - timedelta(days=1), settlement_to)
            chunks.append(
                {"settlementDateFrom": cursor.isoformat(), "settlementDateTo": end.isoformat(), "fuelType": "WIND"}
            )
            cursor = end + timedelta(days=1)
        return await self._fetch_all("/datasets/FUELHH/stream", chunks)

    async def fetch_forecasts(self, publish_from: datetime, publish_to: datetime) -> list[dict]:
        """WINDFOR forecasts published in [publish_from, publish_to)."""
        chunks = []
        cursor = publish_from
        while cursor < publish_to:
            end = min(cursor + self._chunk, publish_to)
            chunks.append({"publishDateTimeFrom": _iso(cursor), "publishDateTimeTo": _iso(end)})
            cursor = end
        return await self._fetch_all("/datasets/WINDFOR/stream", chunks)

    async def _fetch_all(self, path: str, chunks: list[dict]) -> list[dict]:
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout, transport=self._transport
        ) as client:
            results = await asyncio.gather(*(self._get(client, path, params) for params in chunks))
        return [row for chunk in results for row in chunk]

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict) -> list[dict]:
        for attempt in range(1, self._retries + 1):
            try:
                response = await client.get(path, params=params)
                response.raise_for_status()
                payload = response.json()
                # Stream endpoints return a bare list; non-stream ones wrap rows in {"data": [...]}.
                return payload["data"] if isinstance(payload, dict) else payload
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt == self._retries or not _is_retryable(exc):
                    raise
                delay = self._backoff * 2 ** (attempt - 1)
                logger.warning("Elexon %s %s failed (%s); retrying in %ss", path, params, exc, delay)
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return True  # network-level errors


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_actuals(records: list[dict]) -> pd.DataFrame:
    """FUELHH records -> one row per half-hour: start_time (UTC), generation (MW)."""
    df = pd.DataFrame.from_records(records)
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in ACTUAL_COLUMNS}).astype(
            {"start_time": "datetime64[ns, UTC]"}
        )
    if "fuelType" in df:
        df = df[df["fuelType"] == "WIND"]
    df = df.assign(
        start_time=pd.to_datetime(df["startTime"], utc=True),
        publish_time=pd.to_datetime(df["publishTime"], utc=True),
        generation=pd.to_numeric(df["generation"], errors="coerce"),
    ).dropna(subset=["generation"])
    # If a period was re-published, keep the most recent value.
    df = df.sort_values("publish_time").drop_duplicates("start_time", keep="last")
    return df.sort_values("start_time")[ACTUAL_COLUMNS].reset_index(drop=True)


def parse_forecasts(records: list[dict]) -> pd.DataFrame:
    """WINDFOR records -> (publish_time, start_time, generation, horizon_h), true forecasts only.

    Each WINDFOR publish also repeats ~24h of already-elapsed hours; those rows have a
    negative horizon and are not forecasts, so they are dropped.
    """
    df = pd.DataFrame.from_records(records)
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in FORECAST_COLUMNS}).astype(
            {"publish_time": "datetime64[ns, UTC]", "start_time": "datetime64[ns, UTC]"}
        )
    df = df.assign(
        start_time=pd.to_datetime(df["startTime"], utc=True),
        publish_time=pd.to_datetime(df["publishTime"], utc=True),
        generation=pd.to_numeric(df["generation"], errors="coerce"),
    ).dropna(subset=["generation"])
    df = df.drop_duplicates(["publish_time", "start_time"], keep="last")
    df["horizon_h"] = (df["start_time"] - df["publish_time"]) / pd.Timedelta(hours=1)
    df = df[df["horizon_h"] >= 0]
    return df.sort_values(["publish_time", "start_time"])[FORECAST_COLUMNS].reset_index(drop=True)
