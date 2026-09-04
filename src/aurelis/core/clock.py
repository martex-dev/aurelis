"""Time, as an injected dependency.

Nothing in Aurelis calls ``datetime.now()``. Every timestamp comes from a
``Clock``, for two reasons that matter more here than in most systems:

**Reproducibility.** A run's artifact hash must depend on its inputs and its
seed, never on when it happened. Wall-clock time reaching a hash by accident
is a whole class of irreproducibility, and the cheapest defence is to make
time an argument.

**Bitemporality.** Market records carry both when a fact was true and when the
company learned it. Two different clocks in principle, and code that reaches
for the ambient one will silently collapse them.

Everything is UTC and timezone-aware. A naive datetime is a bug, and
:func:`ensure_utc` says so rather than guessing what zone was meant.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol

__all__ = ["Clock", "FrozenClock", "SystemClock", "ensure_utc", "isoformat", "parse_utc"]


class Clock(Protocol):
    """Source of the current instant. Always tz-aware UTC."""

    def now(self) -> dt.datetime: ...


class SystemClock:
    """The real clock. The only place ``datetime.now`` is called."""

    __slots__ = ()

    def now(self) -> dt.datetime:
        return dt.datetime.now(tz=dt.UTC)


class FrozenClock:
    """A clock that does not move unless told to.

    Tests use this so that a timestamp appearing in an assertion is a value
    the test chose, not one the machine supplied.
    """

    __slots__ = ("_now",)

    def __init__(self, now: dt.datetime | None = None) -> None:
        self._now = ensure_utc(now) if now is not None else dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    def now(self) -> dt.datetime:
        return self._now

    def set(self, moment: dt.datetime) -> None:
        self._now = ensure_utc(moment)

    def advance(self, **delta: float) -> dt.datetime:
        """Move forward by a :class:`datetime.timedelta` keyword spec."""
        self._now = self._now + dt.timedelta(**delta)
        return self._now


def ensure_utc(moment: dt.datetime) -> dt.datetime:
    """Return ``moment`` as tz-aware UTC, refusing naive input.

    Refusing rather than assuming is deliberate: a naive datetime in market
    data is ambiguous between exchange local time and UTC, and guessing wrong
    shifts every bar by hours without any error appearing.
    """
    if moment.tzinfo is None:
        raise ValueError(
            "naive datetime rejected: attach a timezone. Aurelis stores UTC everywhere, "
            "and silently assuming a zone is how timestamps drift."
        )
    return moment.astimezone(dt.UTC)


def isoformat(moment: dt.datetime) -> str:
    """Canonical string form: UTC, microseconds, trailing ``Z``.

    Used inside hash preimages, so the format is fixed here rather than left
    to whatever ``str()`` does this release.
    """
    return ensure_utc(moment).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def parse_utc(text: str) -> dt.datetime:
    """Inverse of :func:`isoformat`, tolerant of a ``+00:00`` offset."""
    return ensure_utc(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
