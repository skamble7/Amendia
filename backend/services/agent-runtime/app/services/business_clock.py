# app/services/business_clock.py
"""ADR-064 Phase 2 — the business-hours clock (self-contained, unit-tested).

An SLA with ``clock="business"`` measures elapsed *working* time, not wall time, so a promise that waits on
people does not "breach" overnight or across a weekend. ``add_business_seconds(anchor, seconds, calendar)``
walks forward from ``anchor``, consuming ``seconds`` only inside working windows on working, non-holiday days,
and returns the instant the budget runs out.

V1 ships a SINGLE deployment-configured default calendar (working weekdays + a daily working-hours window +
an optional holiday list, all from ``AGENTRT_SLA_BUSINESS_*`` config). A richer multi-calendar / per-timezone
story (per-cohort or per-owner calendars, DST-correct local windows) is a deliberate later refinement — this
helper is isolated so that swap is contained. Everything here is timezone-naive-in-UTC: the anchor is a UTC
instant and the window bounds are UTC hours.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import FrozenSet

# A hard cap on the forward walk so a mis-configured calendar (e.g. zero working days) can never loop forever;
# ~10 years of days is far beyond any real SLA and turns a bad config into a bounded, obvious wrong answer.
_MAX_DAYS = 3660


@dataclass(frozen=True)
class BusinessCalendar:
    """Working weekdays (0=Mon … 6=Sun), a daily UTC working-hours window, and holiday dates."""
    working_weekdays: FrozenSet[int] = field(default_factory=lambda: frozenset({0, 1, 2, 3, 4}))
    work_start_hour: int = 9
    work_end_hour: int = 17
    holidays: FrozenSet[date] = field(default_factory=frozenset)

    def _is_working_day(self, d: date) -> bool:
        return d.weekday() in self.working_weekdays and d not in self.holidays

    @property
    def _window_seconds(self) -> int:
        return max(0, (self.work_end_hour - self.work_start_hour)) * 3600


def add_business_seconds(anchor: datetime, seconds: int, calendar: BusinessCalendar) -> datetime:
    """Return the instant reached after consuming ``seconds`` of working time from ``anchor``.

    ``seconds <= 0`` returns ``anchor`` unchanged. A calendar with no working days or a zero-length window is a
    mis-configuration; rather than loop, it degrades to wall-clock (``anchor + seconds``) — a loud-in-hindsight
    fallback the caller can detect (the result equals plain wall time)."""
    if seconds <= 0:
        return anchor
    if not calendar.working_weekdays or calendar._window_seconds <= 0:
        return anchor + timedelta(seconds=seconds)

    remaining = seconds
    cur = _as_utc(anchor)
    for _ in range(_MAX_DAYS):
        if not calendar._is_working_day(cur.date()):
            cur = _next_day_open(cur, calendar)
            continue
        day_start = _at(cur, calendar.work_start_hour)
        day_end = _at(cur, calendar.work_end_hour)
        if cur < day_start:
            cur = day_start
        if cur >= day_end:
            cur = _next_day_open(cur, calendar)
            continue
        avail = int((day_end - cur).total_seconds())
        if remaining <= avail:
            return cur + timedelta(seconds=remaining)
        remaining -= avail
        cur = _next_day_open(cur, calendar)
    # Unreachable for any sane config (guarded above); bounded fallback rather than a hang.
    return cur


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _at(dt: datetime, hour: int) -> datetime:
    return datetime.combine(dt.date(), time(hour=hour), tzinfo=dt.tzinfo)


def _next_day_open(dt: datetime, calendar: BusinessCalendar) -> datetime:
    return _at(dt + timedelta(days=1), calendar.work_start_hour)


def calendar_from_settings(settings) -> BusinessCalendar:
    """Build the single default calendar from ``AGENTRT_SLA_BUSINESS_*`` config."""
    days = frozenset(
        int(x) for x in str(settings.SLA_BUSINESS_DAYS).split(",") if str(x).strip() != ""
    )
    holidays = frozenset(
        date.fromisoformat(x.strip())
        for x in str(settings.SLA_BUSINESS_HOLIDAYS).split(",") if x.strip() != ""
    )
    return BusinessCalendar(
        working_weekdays=days,
        work_start_hour=int(settings.SLA_BUSINESS_START_HOUR),
        work_end_hour=int(settings.SLA_BUSINESS_END_HOUR),
        holidays=holidays,
    )
