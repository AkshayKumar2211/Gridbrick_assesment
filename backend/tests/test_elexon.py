from datetime import UTC, date, datetime

import httpx
import pytest

from app.elexon import ElexonClient, parse_actuals, parse_forecasts


def test_parse_forecasts_drops_elapsed_hours_and_duplicates():
    rows = [
        {"publishTime": "2026-01-10T09:30:00Z", "startTime": "2026-01-10T09:00:00Z", "generation": 1},  # past
        {"publishTime": "2026-01-10T09:30:00Z", "startTime": "2026-01-10T10:00:00Z", "generation": 2},
        {"publishTime": "2026-01-10T09:30:00Z", "startTime": "2026-01-10T10:00:00Z", "generation": 3},  # dup
        {"publishTime": "2026-01-10T09:30:00Z", "startTime": "2026-01-10T11:00:00Z", "generation": None},
    ]
    df = parse_forecasts(rows)
    assert len(df) == 1
    assert df.loc[0, "generation"] == 3 and df.loc[0, "horizon_h"] == 0.5


def test_parse_actuals_keeps_wind_and_latest_publish():
    rows = [
        {
            "publishTime": "2026-01-10T10:30:00Z",
            "startTime": "2026-01-10T10:00:00Z",
            "fuelType": "WIND",
            "generation": 5,
        },
        {
            "publishTime": "2026-01-10T11:00:00Z",
            "startTime": "2026-01-10T10:00:00Z",
            "fuelType": "WIND",
            "generation": 6,
        },
        {
            "publishTime": "2026-01-10T10:30:00Z",
            "startTime": "2026-01-10T10:00:00Z",
            "fuelType": "CCGT",
            "generation": 9,
        },
    ]
    df = parse_actuals(rows)
    assert list(df["generation"]) == [6]


def test_parse_handles_empty_payload():
    assert parse_actuals([]).empty and parse_forecasts([]).empty


async def test_client_chunks_requests_and_retries_server_errors():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"startTime": request.url.params["settlementDateFrom"]}])

    client = ElexonClient(
        "https://example.test", retries=3, chunk_days=14, backoff_s=0, transport=httpx.MockTransport(handler)
    )
    rows = await client.fetch_actuals(date(2026, 1, 1), date(2026, 1, 31))

    # 31 days in 14-day chunks -> 3 chunks, plus one retry
    assert len(rows) == 3
    assert len(calls) == 4
    assert all(c["fuelType"] == "WIND" for c in calls)
    assert sorted(r["startTime"] for r in rows) == ["2026-01-01", "2026-01-15", "2026-01-29"]


async def test_client_does_not_retry_client_errors():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400)

    client = ElexonClient("https://example.test", retries=3, transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await client.fetch_forecasts(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
    assert attempts == 1
