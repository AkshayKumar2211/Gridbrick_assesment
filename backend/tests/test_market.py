from datetime import UTC, date, datetime, time, timedelta

import pandas as pd

from app.market import MarketCalendar, to_utc

cal = MarketCalendar(delivery_day_start_hour=23)


def test_winter_delivery_window_runs_23_to_23_uk_time():
    assert cal.delivery_window(date(2026, 1, 15)) == (
        datetime(2026, 1, 14, 23, tzinfo=UTC),
        datetime(2026, 1, 15, 23, tzinfo=UTC),
    )


def test_summer_delivery_window_respects_bst():
    start, end = cal.delivery_window(date(2026, 7, 15))
    assert start == datetime(2026, 7, 14, 22, tzinfo=UTC)
    assert end == datetime(2026, 7, 15, 22, tzinfo=UTC)


def test_clock_change_day_is_23_hours_long():
    start, end = cal.delivery_window(date(2026, 3, 29))  # clocks go forward at 01:00 GMT
    assert end - start == timedelta(hours=23)


def test_decision_is_taken_on_the_previous_day_in_uk_time():
    assert cal.decision_at(date(2026, 1, 15), time(9, 50)) == datetime(2026, 1, 14, 9, 50, tzinfo=UTC)
    assert cal.decision_at(date(2026, 7, 15), time(9, 50)) == datetime(2026, 7, 14, 8, 50, tzinfo=UTC)


def test_delivery_date_of_timestamps():
    ts = pd.Series(pd.to_datetime(["2026-01-14T22:30Z", "2026-01-14T23:00Z", "2026-01-15T22:30Z"], utc=True))
    assert list(cal.delivery_dates_of(ts)) == [date(2026, 1, 14), date(2026, 1, 15), date(2026, 1, 15)]


def test_calendar_day_mode():
    calendar_days = MarketCalendar(delivery_day_start_hour=0)
    assert calendar_days.delivery_window(date(2026, 1, 15))[0] == datetime(2026, 1, 15, tzinfo=UTC)
    ts = pd.Series(pd.to_datetime(["2026-01-14T23:00Z"], utc=True))
    assert list(calendar_days.delivery_dates_of(ts)) == [date(2026, 1, 14)]


def test_naive_datetimes_are_uk_local():
    assert to_utc(datetime(2026, 7, 1, 12, 0)) == datetime(2026, 7, 1, 11, 0, tzinfo=UTC)
    assert to_utc(datetime(2026, 1, 1, 12, 0)) == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
