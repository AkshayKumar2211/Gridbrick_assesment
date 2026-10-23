"""GB day-ahead market calendar: delivery windows and decision times.

All calendar logic is expressed in UK local time (Europe/London) and converted to
UTC at the boundary, so it stays correct across clock changes.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

UK_TZ = ZoneInfo("Europe/London")

# GB day-ahead auction gate closures (UK local time on D-1). NESO's WINDFOR forecast
# is re-published at ~09:30, i.e. between the two - see the decision-time profile.
DECISION_PRESETS = [
    {"label": "EPEX GB hourly auction", "time": "09:20"},
    {"label": "N2EX GB auction", "time": "09:50"},
]


def to_utc(dt: datetime) -> datetime:
    """Interpret a naive datetime as UK local time; convert any datetime to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UK_TZ)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class MarketCalendar:
    # Delivery day D starts at this hour (UK local) on D-1. 23 matches the GB
    # day-ahead auctions; 0 would mean plain calendar days.
    delivery_day_start_hour: int = 23

    def day_start(self, delivery_date: date) -> datetime:
        """UTC instant at which delivery day `delivery_date` starts."""
        if self.delivery_day_start_hour == 0:
            local = datetime.combine(delivery_date, time(0), tzinfo=UK_TZ)
        else:
            local = datetime.combine(
                delivery_date - timedelta(days=1), time(self.delivery_day_start_hour), tzinfo=UK_TZ
            )
        return local.astimezone(UTC)

    def delivery_window(self, delivery_date: date) -> tuple[datetime, datetime]:
        """UTC [start, end) of a delivery day."""
        return self.day_start(delivery_date), self.day_start(delivery_date + timedelta(days=1))

    def decision_at(self, delivery_date: date, decision_time: time) -> datetime:
        """UTC instant of the purchase decision for `delivery_date` (made on D-1, UK local)."""
        local = datetime.combine(delivery_date - timedelta(days=1), decision_time, tzinfo=UK_TZ)
        return local.astimezone(UTC)

    def delivery_dates_of(self, start_times: pd.Series) -> pd.Series:
        """Vectorised: the delivery date each UTC timestamp belongs to."""
        local = start_times.dt.tz_convert(UK_TZ)
        dates = local.dt.normalize().dt.tz_localize(None)
        if self.delivery_day_start_hour:
            dates = dates + pd.to_timedelta((local.dt.hour >= self.delivery_day_start_hour).astype(int), unit="D")
        return dates.dt.date
