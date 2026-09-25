"""One pace per vendor, shared by every reader in the process.

A free vendor's rate limit is per caller, not per reader. GeckoTerminal is
read by the token follower (a pool lookup and a candle read per token) and by
the trending-pools source in the same wake. Each paced itself, so together
they ran at twice the vendor's limit, and the live wake of 2026-09-25 was
refused on tokens it had read the hour before. A reader now asks the process
for its turn, and a refusal is waited out for as long as the vendor asks.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

__all__ = ["BACKOFF_CAP", "pace", "retry_after"]

#: The longest a refusal is waited out, whatever the vendor asks: a wake has
#: other work, and a token not read this hour is read next hour.
BACKOFF_CAP = 90.0

_LOCK = threading.Lock()
_LAST: dict[str, float] = {}


def pace(
    vendor: str,
    interval: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> None:
    """Wait until ``interval`` seconds have passed since this vendor's last call."""
    if interval <= 0:
        return
    with _LOCK:
        last = _LAST.get(vendor)
        if last is not None:
            wait = last + interval - now()
            if wait > 0:
                sleep(wait)
        _LAST[vendor] = now()


def retry_after(error: Any, default: float) -> float:
    """The wait a 429 asks for, from its ``Retry-After`` header, capped."""
    headers = getattr(error, "headers", None)
    raw = headers.get("Retry-After") if headers is not None else None
    try:
        asked = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        asked = default
    return max(0.0, min(asked, BACKOFF_CAP))
