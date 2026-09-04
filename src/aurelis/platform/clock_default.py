"""The process-wide clock.

Everything takes a ``Clock`` as an argument; this is the default that
composition roots hand in, and the one place a test can swap for a
:class:`~aurelis.core.clock.FrozenClock` without threading one through every
constructor.

Not a singleton anyone reaches for directly: code that reads the time takes a
clock. This exists so wiring code has something to pass.
"""

from __future__ import annotations

from aurelis.core.clock import Clock, SystemClock

__all__ = ["default_clock", "set_default_clock"]

_clock: Clock = SystemClock()


def default_clock() -> Clock:
    return _clock


def set_default_clock(clock: Clock) -> Clock:
    """Replace the default and return the previous one, so it can be restored."""
    global _clock
    previous, _clock = _clock, clock
    return previous
