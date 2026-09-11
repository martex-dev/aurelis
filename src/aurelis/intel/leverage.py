"""Funding and open interest, recorded as events on the spot instrument.

Both live mechanisms reason about leverage — clustered liquidations, forced
flow, over-leveraged longs de-risking — and until this module the company held
no leverage data at all. A causal story about liquidation cascades, told over
closes alone, is a story; told beside the funding rate and the open interest
of the same asset's perpetual, it is checkable, and a mechanism can fire on the
leverage itself.

Bybit publishes, without credentials, every linear perpetual's funding history
(a rate per eight-hour settlement) and its open interest at hourly intervals.
Read every wake for every instrument on a leverage grant, they become events on
the **spot instrument entity** the company already records — ``BTC-USD``, not
``BTCUSDT`` — so that mining can join them to price events on the same entity
and a mechanism triggered by funding seals against the spot close. The
perpetual is recorded as its own entity, ``derivative_of`` the spot instrument,
so a reader can see where the number came from.

``leverage.funding``
    One per settlement: the rate for the period, and annualised.

``leverage.open_interest``
    One per hourly reading: contracts outstanding in base units, and the
    change over the last day.

And the derived kinds, so a mechanism can fire on them: ``funding.extreme_
positive`` / ``funding.extreme_negative`` past ``FUNDING_EXTREME``, and
``oi.surge`` / ``oi.purge`` past ``OI_SURGE`` percent over a day. Every
threshold travels in the event it produced.

A funding settlement is a fact about its settlement instant, so the same
settlement read on two wakes is one event. The raw payloads are stored as one
artifact per reading; its digest is returned to the caller and kept off the
event payloads on purpose — a raw document that grows by one row per fetch
would make every fetch a "new" event.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock
from aurelis.intel.live import USER_AGENT, FeedUnavailable
from aurelis.world.store import World

__all__ = [
    "FUNDING_EXTREME",
    "OI_SURGE",
    "BybitLeverage",
    "Leverage",
    "perp_for",
    "record_leverage",
]

FUNDING_EXTREME = Decimal("0.0005")
"""A funding rate per settlement at or past this, either sign, is
``funding.extreme_positive`` / ``funding.extreme_negative``. Five basis points
per eight hours is about fifty-five percent a year: longs (or shorts) paying
that to stay in are crowded."""

OI_SURGE = Decimal("10")
"""Open interest up at least this percent over a day is ``oi.surge``; down at
least this much is ``oi.purge``."""

_SETTLEMENTS_A_YEAR = Decimal(3 * 365)
_Q = Decimal("0.00000001")


def perp_for(symbol: str) -> str:
    """The linear perpetual for a spot symbol: ``BTC-USD`` reads ``BTCUSDT``."""
    base = symbol.split("-", 1)[0].upper()
    return f"{base}USDT"


def _get(url: str, opener: Any, timeout: int, name: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    fetch = opener or urllib.request.urlopen
    try:
        with fetch(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise FeedUnavailable(f"{name} refused the request ({error.code})") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FeedUnavailable(f"{name} could not be reached: {error}") from error


def _result_list(payload: Any, name: str, what: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("retCode") != 0:
        code = payload.get("retMsg") if isinstance(payload, dict) else type(payload).__name__
        raise FeedUnavailable(f"{name} did not return {what}: {code}")
    rows = (payload.get("result") or {}).get("list")
    if not isinstance(rows, list):
        raise FeedUnavailable(f"{name} returned {what} without a list")
    return [row for row in rows if isinstance(row, dict)]


@dataclass(frozen=True, slots=True)
class BybitLeverage:
    """Bybit's public v5 market endpoints for linear perpetuals. No credentials."""

    name: str = "bybit"
    endpoint: str = "https://api.bybit.com/v5/market"
    timeout: int = 25
    opener: Any = None

    def listed(self) -> frozenset[str]:
        """Every USDT linear perpetual that is trading. One call."""
        payload = _get(
            f"{self.endpoint}/instruments-info?category=linear&limit=1000",
            self.opener,
            self.timeout,
            self.name,
        )
        rows = _result_list(payload, self.name, "instruments")
        return frozenset(
            str(row["symbol"])
            for row in rows
            if row.get("quoteCoin") == "USDT" and row.get("status") == "Trading"
        )

    def funding(self, perp: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Recent settlements, newest first."""
        payload = _get(
            f"{self.endpoint}/funding/history?category=linear&symbol={perp}&limit={limit}",
            self.opener,
            self.timeout,
            self.name,
        )
        return _result_list(payload, self.name, f"funding for {perp}")

    def open_interest(self, perp: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Hourly readings, newest first. Twenty-five covers a day and its start."""
        payload = _get(
            f"{self.endpoint}/open-interest?category=linear&symbol={perp}"
            f"&intervalTime=1h&limit={limit}",
            self.opener,
            self.timeout,
            self.name,
        )
        return _result_list(payload, self.name, f"open interest for {perp}")


@dataclass(frozen=True, slots=True)
class Leverage:
    """One reading of one instrument's perpetual."""

    symbol: str
    perp: str
    funding_at: dt.datetime
    funding_rate: Decimal
    """Per settlement, as the venue quotes it: ``0.0001`` is a basis point."""

    funding_annualised_pct: Decimal
    open_interest_at: dt.datetime
    open_interest: Decimal
    """Contracts outstanding, in base units."""

    open_interest_change_24h_pct: Decimal | None
    raw_digest: str

    def describe(self) -> str:
        change = (
            f"{self.open_interest_change_24h_pct:+}% over 24h"
            if self.open_interest_change_24h_pct is not None
            else "no 24h comparison"
        )
        return (
            f"{self.symbol} via {self.perp}: funding {self.funding_rate} "
            f"({self.funding_annualised_pct}% a year), open interest "
            f"{self.open_interest} ({change})"
        )


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise FeedUnavailable(f"{value!r} is not a number") from error


def _at_ms(value: Any) -> dt.datetime:
    return dt.datetime.fromtimestamp(int(str(value)) / 1000, tz=dt.UTC)


def read(
    symbol: str, perp: str, funding: list[dict[str, Any]], oi: list[dict[str, Any]]
) -> Leverage:
    if not funding:
        raise FeedUnavailable(f"no funding settlement for {perp}")
    if not oi:
        raise FeedUnavailable(f"no open interest reading for {perp}")
    latest_funding = funding[0]
    rate = _decimal(latest_funding["fundingRate"])
    latest_oi = oi[0]
    now_oi = _decimal(latest_oi["openInterest"])
    now_at = _at_ms(latest_oi["timestamp"])
    change: Decimal | None = None
    day_ago = now_at - dt.timedelta(hours=24)
    earlier = [row for row in oi[1:] if _at_ms(row["timestamp"]) <= day_ago]
    if earlier:
        base = _decimal(earlier[0]["openInterest"])
        if base > 0:
            change = ((now_oi / base - 1) * 100).quantize(Decimal("0.01"))
    return Leverage(
        symbol=symbol,
        perp=perp,
        funding_at=_at_ms(latest_funding["fundingRateTimestamp"]),
        funding_rate=rate.quantize(_Q),
        funding_annualised_pct=(rate * _SETTLEMENTS_A_YEAR * 100).quantize(Decimal("0.01")),
        open_interest_at=now_at,
        open_interest=now_oi.quantize(Decimal("0.001")),
        open_interest_change_24h_pct=change,
        raw_digest="",
    )


def record_leverage(
    session: Session,
    world: World,
    artifacts: Any,
    *,
    symbol: str,
    feed: BybitLeverage,
    clock: Clock,
    at: dt.datetime | None = None,
) -> tuple[Leverage, int]:
    """Fetch once, store the raw payloads, record the events on the spot instrument.

    Returns the reading and how many events were new. The funding event's
    ``at`` is the settlement instant and the open-interest event's is the
    reading's own timestamp — facts about those instants, which is what makes
    the same settlement read twice one event.
    """
    moment = at or clock.now()
    perp = perp_for(symbol)
    funding = feed.funding(perp)
    oi = feed.open_interest(perp)
    reading = read(symbol, perp, funding, oi)

    raw = artifacts.put_json(
        session,
        {"symbol": symbol, "perp": perp, "at": moment.isoformat(), "funding": funding, "oi": oi},
        kind="leverage.raw",
        produced_by=feed.name,
    )
    reading = replace(reading, raw_digest=raw.digest)
    source = f"{feed.endpoint}/{perp}"
    world.see(session, kind="venue", key=feed.name, name=feed.name, source=source, at=moment)
    world.see(session, kind="instrument", key=symbol, source=source, at=moment)
    world.see(
        session,
        kind="instrument",
        key=perp,
        name=perp,
        attributes={"venue": feed.name, "contract": "linear_perpetual", "quote": "USDT"},
        source=source,
        at=moment,
    )
    world.relate(
        session,
        subject=("instrument", perp),
        kind="listed_on",
        obj=("venue", feed.name),
        source=source,
        at=moment,
    )
    world.relate(
        session,
        subject=("instrument", perp),
        kind="derivative_of",
        obj=("instrument", symbol),
        source=source,
        at=moment,
    )

    new = 0
    _, created = world.record(
        session,
        kind="leverage.funding",
        at=reading.funding_at,
        entity_kind="instrument",
        entity_key=symbol,
        payload={
            "venue": feed.name,
            "perp": perp,
            "rate": str(reading.funding_rate),
            "annualised_pct": str(reading.funding_annualised_pct),
        },
        source=source,
        recorded_at=moment,
    )
    new += int(created)
    oi_payload: dict[str, Any] = {
        "venue": feed.name,
        "perp": perp,
        "open_interest": str(reading.open_interest),
    }
    if reading.open_interest_change_24h_pct is not None:
        oi_payload["change_24h_pct"] = str(reading.open_interest_change_24h_pct)
    _, created = world.record(
        session,
        kind="leverage.open_interest",
        at=reading.open_interest_at,
        entity_kind="instrument",
        entity_key=symbol,
        payload=oi_payload,
        source=source,
        recorded_at=moment,
    )
    new += int(created)

    derived: list[tuple[str, dt.datetime, dict[str, Any]]] = []
    if reading.funding_rate >= FUNDING_EXTREME:
        derived.append(
            (
                "funding.extreme_positive",
                reading.funding_at,
                {"rate": str(reading.funding_rate), "threshold": str(FUNDING_EXTREME)},
            )
        )
    elif reading.funding_rate <= -FUNDING_EXTREME:
        derived.append(
            (
                "funding.extreme_negative",
                reading.funding_at,
                {"rate": str(reading.funding_rate), "threshold": str(-FUNDING_EXTREME)},
            )
        )
    change = reading.open_interest_change_24h_pct
    if change is not None and change >= OI_SURGE:
        derived.append(
            (
                "oi.surge",
                reading.open_interest_at,
                {"change_24h_pct": str(change), "threshold": str(OI_SURGE)},
            )
        )
    elif change is not None and change <= -OI_SURGE:
        derived.append(
            (
                "oi.purge",
                reading.open_interest_at,
                {"change_24h_pct": str(change), "threshold": str(-OI_SURGE)},
            )
        )
    for kind, when, payload in derived:
        _, created = world.record(
            session,
            kind=kind,
            at=when,
            entity_kind="instrument",
            entity_key=symbol,
            payload={**payload, "venue": feed.name, "perp": perp},
            source=source,
            recorded_at=moment,
        )
        new += int(created)
    return reading, new
