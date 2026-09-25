"""M48 — one vendor, one pace, whichever reader is asking.

* two readers of the same vendor share one interval between calls,
* a refusal is waited out for as long as the vendor asks, and no longer than
  the cap,
* the token reader tries three times before it gives up on a 429.

**Nothing here touches the network.**
"""

from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from typing import Any

import pytest

from aurelis.intel import pacing
from aurelis.intel.dex import GeckoTerminalCandles
from aurelis.intel.live import FeedUnavailable
from aurelis.intel.pacing import BACKOFF_CAP, pace, retry_after


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.t += seconds


def test_two_readers_of_one_vendor_share_one_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pacing, "_LAST", {})
    clock = _Clock()
    pace("vendor", 2.0, sleep=clock.sleep, now=clock.now)  # the token reader
    clock.t += 0.5
    pace("vendor", 2.0, sleep=clock.sleep, now=clock.now)  # the trending reader
    pace("other", 2.0, sleep=clock.sleep, now=clock.now)  # a different vendor waits for nobody
    assert clock.slept == [1.5]


def _refusal(after: str | None) -> urllib.error.HTTPError:
    headers = Message()
    if after is not None:
        headers["Retry-After"] = after
    return urllib.error.HTTPError("https://x", 429, "Too Many Requests", headers, None)


def test_a_refusal_is_waited_out_as_long_as_the_vendor_asks_and_no_longer_than_the_cap() -> None:
    assert retry_after(_refusal("12"), 30) == 12
    assert retry_after(_refusal(None), 30) == 30
    assert retry_after(_refusal("soon"), 30) == 30
    assert retry_after(_refusal("3600"), 30) == BACKOFF_CAP


def test_the_token_reader_tries_three_times_before_it_gives_up_on_a_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def refuse_twice(request: Any, timeout: int = 0) -> Any:  # noqa: ARG001
        calls.append(request.full_url)
        if len(calls) < 3:
            raise _refusal("1")
        return io.BytesIO(json.dumps({"data": []}).encode())

    feed = GeckoTerminalCandles(pause=0, opener=refuse_twice)
    assert feed._get("https://api.geckoterminal.com/api/v2/x") == {"data": []}
    assert len(calls) == 3

    calls.clear()

    def refuse(request: Any, timeout: int = 0) -> Any:  # noqa: ARG001
        calls.append(request.full_url)
        raise _refusal("1")

    with pytest.raises(FeedUnavailable, match="429"):
        GeckoTerminalCandles(pause=0, opener=refuse)._get("https://api.geckoterminal.com/y")
    assert len(calls) == 3
