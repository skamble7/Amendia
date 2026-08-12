# tests/test_business_clock.py
"""ADR-064 P2 — the business-hours clock (isolated, deterministic, no I/O)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.services.business_clock import BusinessCalendar, add_business_seconds, calendar_from_settings

# Mon–Fri, 09:00–17:00 UTC (an 8h/28800s working day), no holidays.
CAL = BusinessCalendar()
H = 3600


def _dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_wall_within_one_working_day():
    # Wed 10:00 + 3 business hours = Wed 13:00 (whole window available).
    assert add_business_seconds(_dt(2026, 8, 12, 10), 3 * H, CAL) == _dt(2026, 8, 12, 13)


def test_rolls_to_next_working_morning_when_window_exhausted():
    # Wed 16:00 + 3 business hours: 1h left today (→17:00), 2h spill to Thu 09:00 → Thu 11:00.
    assert add_business_seconds(_dt(2026, 8, 12, 16), 3 * H, CAL) == _dt(2026, 8, 13, 11)


def test_before_work_start_clamps_to_open():
    # Wed 06:00 + 2 business hours starts the clock at 09:00 → Wed 11:00.
    assert add_business_seconds(_dt(2026, 8, 12, 6), 2 * H, CAL) == _dt(2026, 8, 12, 11)


def test_skips_the_weekend():
    # Fri 16:00 + 2 business hours: 1h Fri (→17:00), then 1h Mon 09:00 → Mon 10:00 (Sat/Sun skipped).
    assert add_business_seconds(_dt(2026, 8, 14, 16), 2 * H, CAL) == _dt(2026, 8, 17, 10)


def test_skips_a_configured_holiday():
    cal = BusinessCalendar(holidays=frozenset({date(2026, 8, 13)}))  # Thu is a holiday
    # Wed 16:00 + 3 business hours: 1h Wed, then Thu skipped → Fri 09:00 + 2h = Fri 11:00.
    assert add_business_seconds(_dt(2026, 8, 12, 16), 3 * H, cal) == _dt(2026, 8, 14, 11)


def test_full_working_day_equivalence():
    # 8 business hours from Wed open lands exactly at Wed close (whole window).
    assert add_business_seconds(_dt(2026, 8, 12, 9), 8 * H, CAL) == _dt(2026, 8, 12, 17)


def test_business_differs_from_wall_across_a_non_working_window():
    anchor = _dt(2026, 8, 14, 16)                 # Fri 16:00
    biz = add_business_seconds(anchor, 2 * H, CAL)  # Mon 10:00
    wall = anchor.replace(hour=18)                # wall +2h = Fri 18:00
    assert biz != wall and biz == _dt(2026, 8, 17, 10)


def test_zero_and_negative_are_identity():
    anchor = _dt(2026, 8, 12, 10)
    assert add_business_seconds(anchor, 0, CAL) == anchor
    assert add_business_seconds(anchor, -5, CAL) == anchor


def test_misconfigured_calendar_degrades_to_wall():
    empty = BusinessCalendar(working_weekdays=frozenset())
    anchor = _dt(2026, 8, 12, 10)
    assert add_business_seconds(anchor, 3 * H, empty) == _dt(2026, 8, 12, 13)  # == wall


def test_calendar_from_settings_parses_config():
    from types import SimpleNamespace
    s = SimpleNamespace(SLA_BUSINESS_DAYS="0,1,2,3,4", SLA_BUSINESS_START_HOUR=8,
                        SLA_BUSINESS_END_HOUR=16, SLA_BUSINESS_HOLIDAYS="2026-12-25, 2027-01-01")
    cal = calendar_from_settings(s)
    assert cal.working_weekdays == frozenset({0, 1, 2, 3, 4})
    assert cal.work_start_hour == 8 and cal.work_end_hour == 16
    assert date(2026, 12, 25) in cal.holidays and date(2027, 1, 1) in cal.holidays
