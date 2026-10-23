"""Application settings, overridable through environment variables (or a .env file)."""

from datetime import date, time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Data source -------------------------------------------------------
    elexon_base_url: str = "https://data.elexon.co.uk/bmrs/api/v1"
    # auto     -> fetch live from Elexon, fall back to the bundled snapshot if Elexon is unreachable
    # live     -> Elexon only (fail if unreachable)
    # snapshot -> bundled snapshot only (offline / deterministic demos)
    data_source: Literal["auto", "live", "snapshot"] = "auto"
    snapshot_path: Path = BACKEND_DIR / "data" / "snapshot.json.gz"
    request_timeout_s: float = 30.0
    request_retries: int = 3
    fetch_chunk_days: int = 14

    # --- Business scope ----------------------------------------------------
    # Purchase decisions made on these (UK local) dates are in scope. A decision on
    # D-1 buys power for delivery day D, so delivery days run one day later.
    decision_date_from: date = date(2026, 1, 1)
    decision_date_to: date = date(2026, 1, 31)
    # N2EX GB day-ahead auction gate closure (UK local time on D-1).
    default_decision_time: time = time(9, 50)
    # GB day-ahead delivery day D runs 23:00 (D-1) -> 23:00 (D) UK time. Set to 0 for calendar days.
    delivery_day_start_hour: int = 23
    # Uncertainty bands are built from forecast errors observed in this trailing window.
    error_lookback_days: int = 14
    max_horizon_hours: int = 48

    # --- API ---------------------------------------------------------------
    cors_origins: str = "*"  # comma-separated list of allowed origins
    # How long a request waits for the initial data load before returning 503.
    # Kept below Heroku's 30 s router timeout.
    data_wait_timeout_s: float = 25.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
