"""HTTP routes. Thin layer: validate inputs, delegate to AnalysisService."""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from .market import to_utc
from .schemas import (
    AccuracyResponse,
    DayAheadResponse,
    DecisionTimeRow,
    ExplorerResponse,
    HealthResponse,
    HorizonRow,
    MetaResponse,
)
from .service import AnalysisService
from .store import DataNotReady, DataStore

router = APIRouter(prefix="/api")

MAX_EXPLORER_DAYS = 32


def get_store(request: Request) -> DataStore:
    return request.app.state.store


async def get_service(store: Annotated[DataStore, Depends(get_store)]) -> AnalysisService:
    try:
        return await store.get_service(store.settings.data_wait_timeout_s)
    except DataNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"}) from exc


Service = Annotated[AnalysisService, Depends(get_service)]


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _check_decision_time(service: AnalysisService, decision_time: time | None) -> time:
    decision_time = decision_time or service.settings.default_decision_time
    start_hour = service.settings.delivery_day_start_hour
    if start_hour and decision_time >= time(start_hour):
        raise _bad_request(f"decision_time must be before {start_hour:02d}:00, when the delivery day starts.")
    return decision_time


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health(store: Annotated[DataStore, Depends(get_store)]):
    return {"status": "ok", "data": store.status, "error": store.error}


@router.get("/meta", response_model=MetaResponse, tags=["system"])
async def meta(service: Service):
    """Data coverage, scope and defaults the UI needs to initialise."""
    return service.meta()


@router.get("/day-ahead", response_model=DayAheadResponse, tags=["day-ahead"])
async def day_ahead(
    service: Service,
    delivery_date: Annotated[date, Query(description="Delivery day D (UK local date)")],
    decision_time: Annotated[
        time | None, Query(description="Decision time on D-1, UK local (HH:MM). Defaults to N2EX gate closure.")
    ] = None,
):
    """Latest wind forecast available at decision time for one delivery day, with
    actual outturn, an empirical uncertainty band and the preceding forecast vintages."""
    if not service.delivery_dates[0] <= delivery_date <= service.delivery_dates[-1]:
        raise _bad_request(
            f"delivery_date must be between {service.delivery_dates[0]} and {service.delivery_dates[-1]}."
        )
    decision_time = _check_decision_time(service, decision_time)
    return await run_in_threadpool(service.day_ahead, delivery_date, decision_time)


@router.get("/explorer", response_model=ExplorerResponse, tags=["explorer"])
async def explorer(
    service: Service,
    start: Annotated[datetime, Query(description="Range start; naive values are UK local time")],
    end: Annotated[datetime, Query(description="Range end (exclusive); naive values are UK local time")],
    horizon_hours: Annotated[float, Query(ge=0, le=48, description="Minimum forecast lead time")] = 4,
):
    """Actual vs the latest forecast published at least `horizon_hours` before each hour."""
    start_utc, end_utc = to_utc(start), to_utc(end)
    if end_utc <= start_utc:
        raise _bad_request("end must be after start.")
    if end_utc - start_utc > timedelta(days=MAX_EXPLORER_DAYS):
        raise _bad_request(f"Range may not exceed {MAX_EXPLORER_DAYS} days.")
    if start_utc < service.scope_start or end_utc > service.scope_end:
        raise _bad_request(
            f"Range must lie within {service.scope_start.isoformat()} - {service.scope_end.isoformat()}."
        )
    return await run_in_threadpool(service.explorer, start_utc, end_utc, horizon_hours)


@router.get("/accuracy", response_model=AccuracyResponse, tags=["accuracy"])
async def accuracy(
    service: Service,
    mode: Literal["day_ahead", "horizon"] = "day_ahead",
    decision_time: Annotated[time | None, Query(description="Used when mode=day_ahead")] = None,
    horizon_hours: Annotated[float, Query(ge=0, le=48, description="Used when mode=horizon")] = 24,
):
    """Accuracy of the forecasts the desk would have used, across every in-scope delivery day."""
    if mode == "day_ahead":
        return await run_in_threadpool(service.accuracy, mode, _check_decision_time(service, decision_time), None)
    return await run_in_threadpool(service.accuracy, mode, None, horizon_hours)


@router.get("/accuracy/horizon-profile", response_model=list[HorizonRow], tags=["accuracy"])
async def horizon_profile(service: Service):
    """Error by forecast lead time (1 h buckets), using every forecast vintage."""
    return await run_in_threadpool(service.horizon_profile)


@router.get("/accuracy/decision-time-profile", response_model=list[DecisionTimeRow], tags=["accuracy"])
async def decision_time_profile(service: Service):
    """Day-ahead accuracy if the purchase decision were taken at each half-hour of D-1."""
    return await run_in_threadpool(service.decision_time_profile)
