# amendia_bpmn/timers.py
"""ISO-8601 timer parsing for BPMN ``timerEventDefinition`` (ADR-027 Phase 2.2).

Framework-free (stdlib only): both the registry (validation/annotation) and the agent-runtime
(computing a durable ``fire_at``) import this so they agree on what a timer means. Supports
``timeDuration`` (ISO-8601 duration) and ``timeDate`` (absolute ISO-8601 instant). ``timeCycle``
(recurring) is recognized but unsupported this rung — callers annotate it, they do not fire it.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from amendia_bpmn.model import TimerDef

# P[nY][nM][nW][nD][T[nH][nM][nS]] — the ISO-8601 duration grammar. Calendar Y/M have no fixed
# length, so we approximate (year=365d, month=30d) — good enough for SLA windows, documented here
# so nobody mistakes it for calendar arithmetic. W/D/H/M/S are exact.
_ISO_DURATION = re.compile(
    r"^P(?!$)(?:(?P<years>\d+(?:\.\d+)?)Y)?(?:(?P<months>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<weeks>\d+(?:\.\d+)?)W)?(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?!$)(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


class UnsupportedTimer(ValueError):
    """The timer definition cannot be turned into a concrete ``fire_at`` (empty, cyclic, malformed)."""


def parse_iso_duration(text: str) -> timedelta:
    """Parse an ISO-8601 duration (``PT4H``, ``PT30M``, ``P1D``, ``P1DT2H30M``) → ``timedelta``.

    Raises :class:`UnsupportedTimer` on malformed input. Y/M are approximated (365d / 30d)."""
    m = _ISO_DURATION.match((text or "").strip())
    if not m:
        raise UnsupportedTimer(f"not an ISO-8601 duration: {text!r}")
    parts = {k: float(v) for k, v in m.groupdict().items() if v is not None}
    if not parts:
        raise UnsupportedTimer(f"empty ISO-8601 duration: {text!r}")
    days = (parts.get("years", 0) * 365 + parts.get("months", 0) * 30
            + parts.get("weeks", 0) * 7 + parts.get("days", 0))
    return timedelta(days=days, hours=parts.get("hours", 0),
                     minutes=parts.get("minutes", 0), seconds=parts.get("seconds", 0))


def _parse_iso_datetime(text: str) -> datetime:
    """Absolute ISO-8601 instant → tz-aware UTC datetime. A bare 'Z' is normalized for
    ``fromisoformat`` on older Pythons; a naive instant is assumed UTC."""
    raw = (text or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise UnsupportedTimer(f"not an ISO-8601 instant: {text!r}") from exc
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def parse_timer(timer: TimerDef, base_now: datetime) -> datetime:
    """Resolve a :class:`TimerDef` to a concrete ``fire_at`` (tz-aware UTC), relative to ``base_now``.

    ``duration`` → ``base_now + delta``; ``date`` → the absolute instant. Raises
    :class:`UnsupportedTimer` for ``cycle``, an empty definition, or malformed text.
    """
    if timer is None or timer.kind is None or timer.value is None:
        raise UnsupportedTimer("timer definition is empty (no timeDuration/timeDate)")
    if timer.kind == "cycle":
        raise UnsupportedTimer(f"timeCycle (recurring timer) is not supported: {timer.value!r}")
    if timer.kind == "duration":
        base = base_now if base_now.tzinfo is not None else base_now.replace(tzinfo=timezone.utc)
        return base + parse_iso_duration(timer.value)
    if timer.kind == "date":
        return _parse_iso_datetime(timer.value)
    raise UnsupportedTimer(f"unknown timer kind {timer.kind!r}")


def timer_is_supported(timer: Optional[TimerDef]) -> bool:
    """True iff :func:`parse_timer` would resolve this timer (a wired duration/date). Used by the
    compilability gate to flag an unsupported/empty timer without computing a ``fire_at``."""
    if timer is None or timer.kind is None or timer.value is None:
        return False
    return timer.kind in ("duration", "date")
