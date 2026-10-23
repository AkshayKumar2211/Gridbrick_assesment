"""Response models. They document the API (see /docs) and validate every payload.

Units: power in MW, energy in MWh, horizons in hours, timestamps ISO-8601 UTC.
Error convention: error = forecast - actual (positive = over-forecast).
"""

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class Range(Model):
    from_: str = Field(alias="from")
    to: str


class Window(Model):
    start: str
    end: str


class ErrorMetrics(Model):
    n: int
    mae: float | None = None
    rmse: float | None = None
    bias: float | None = Field(None, description="Mean of forecast - actual; positive = over-forecast")
    wape_pct: float | None = Field(None, description="Sum |error| / sum actual, in %")
    p50_abs: float | None = None
    p90_abs: float | None = None
    p95_abs: float | None = None
    max_over: float | None = None
    max_under: float | None = None
    correlation: float | None = None
    mean_actual: float | None = None


# --- /api/meta ------------------------------------------------------------------


class Preset(Model):
    label: str
    time: str


class ActualsInfo(Model):
    count: int
    first: str | None
    last: str | None


class ForecastsInfo(Model):
    count: int
    publishes: int
    first_publish: str | None
    last_publish: str | None


class MetaResponse(Model):
    source: str = Field(description="'elexon-live' or 'snapshot'")
    loaded_at: str
    timezone: str
    decision_dates: Range
    delivery_dates: Range
    scope: Window
    delivery_day_start_hour: int
    default_decision_time: str
    decision_time_presets: list[Preset]
    max_horizon_hours: int
    error_lookback_days: int
    publish_schedule: list[str]
    actuals: ActualsInfo
    forecasts: ForecastsInfo


# --- /api/day-ahead -------------------------------------------------------------


class DayAheadPoint(Model):
    time: str
    actual: float | None
    forecast: float | None
    adjusted: float | None = Field(description="Forecast + median recent residual (bias-adjusted)")
    band_low: float | None = Field(description="Forecast + 10th percentile recent residual (low-wind case)")
    band_high: float | None = Field(description="Forecast + 90th percentile recent residual (high-wind case)")


class VintagePoint(Model):
    time: str
    forecast: float | None


class Vintage(Model):
    publish_time: str
    points: list[VintagePoint]


class BandInfo(Model):
    quantiles: list[float]
    lookback_days: int
    horizon_window_h: float
    min_samples: int


class DayAheadSummary(Model):
    forecast_energy_mwh: float | None
    adjusted_energy_mwh: float | None
    low_case_energy_mwh: float | None
    high_case_energy_mwh: float | None
    actual_energy_mwh: float | None
    energy_error_mwh: float | None
    actual_complete: bool
    band_coverage_pct: float | None
    metrics: ErrorMetrics
    adjusted_metrics: ErrorMetrics


class DayAheadResponse(Model):
    delivery_date: str
    decision_time: str
    decision_at: str
    window: Window
    forecast_publish_time: str | None
    forecast_age_minutes: int | None
    horizon_range_h: list[float | None]
    band: BandInfo
    summary: DayAheadSummary
    points: list[DayAheadPoint]
    earlier_forecasts: list[Vintage]


# --- /api/explorer --------------------------------------------------------------


class ExplorerPoint(Model):
    time: str
    actual: float | None
    forecast: float | None
    publish_time: str | None
    horizon_h: float | None


class ExplorerResponse(Model):
    start: str
    end: str
    horizon_hours: float
    metrics: ErrorMetrics
    points: list[ExplorerPoint]


# --- /api/accuracy --------------------------------------------------------------


class Selection(Model):
    mode: str
    decision_time: str | None
    horizon_hours: float | None
    label: str
    mean_horizon_h: float | None


class SignedQuantiles(Model):
    p05: float | None
    p10: float | None
    p25: float | None
    p50: float | None
    p75: float | None
    p90: float | None
    p95: float | None


class DailyRow(Model):
    delivery_date: str
    mae: float | None
    bias: float | None
    max_abs_error: float | None
    forecast_energy_mwh: float | None
    actual_energy_mwh: float | None
    energy_error_mwh: float | None
    adjusted_energy_error_mwh: float | None


class HourRow(Model):
    hour: int
    n: int
    mae: float | None
    bias: float | None
    p10: float | None
    p90: float | None


class HistogramBin(Model):
    lo: float
    hi: float
    count: int


class ScatterPoint(Model):
    time: str
    forecast: float | None
    actual: float | None


class AccuracyResponse(Model):
    selection: Selection
    metrics: ErrorMetrics
    adjusted_metrics: ErrorMetrics | None = Field(description="Bias-adjusted forecast; day_ahead mode only")
    band_coverage_pct: float | None = Field(description="% of hours inside the 10-90% band; day_ahead mode only")
    signed_error_quantiles: SignedQuantiles
    daily: list[DailyRow]
    by_hour: list[HourRow]
    histogram: list[HistogramBin]
    scatter: list[ScatterPoint]


class HorizonRow(Model):
    horizon_h: float
    n: int
    mae: float | None
    rmse: float | None
    bias: float | None
    p10: float | None
    p90: float | None


class DecisionTimeRow(Model):
    decision_time: str
    mae: float | None
    rmse: float | None
    bias: float | None
    n: int
    typical_publish_time: str | None
    mean_horizon_h: float | None


class HealthResponse(Model):
    status: str
    data: str = Field(description="ready | loading | error | idle")
    error: str | None = None
