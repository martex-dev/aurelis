"""A price recording per token, from the pool it trades in, and who is followed.

The memecoin desk's instruments are tokens named by chain and contract,
``<network>:<address>`` — the key the attention sources already record
boosts and trending on (M43). A token has no exchange candle endpoint; it
has pools, and GeckoTerminal publishes each pool's OHLCV without a
credential. :class:`GeckoTerminalCandles` satisfies the same
:class:`~aurelis.intel.live.CandleFeed` protocol as the Coinbase adapter,
so a token's bars enter through the same ingestion, are hashed the same
way, and derive the same price events.

Which tokens are followed is not a list a person types: a memecoin that is
worth following today is dead in a week, and a fixed list would be a list
of corpses. A ``dex`` grant names the networks and the rule — follow up to
N tokens the attention sources surfaced in the last K days, most liquid
first — and the wake evaluates the rule against the record. The person
grants the class and the caps; the agents' chosen sources decide the
names; the rule is on the grant so a reader knows what the service may do.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.errors import IntegrityViolation
from aurelis.intel.live import USER_AGENT, FeedUnavailable
from aurelis.intel.sources import Bar
from aurelis.world.tables import Entity, WorldEvent

__all__ = [
    "ATTENTION_KINDS",
    "DexRule",
    "GeckoTerminalCandles",
    "followed_tokens",
    "names_of",
    "split_key",
]

ATTENTION_KINDS: tuple[str, ...] = ("attention.boost", "dex.trending")
"""The events that put a token on the desk's list."""

_TIMEFRAMES: dict[str, tuple[str, int]] = {
    "1m": ("minute", 1),
    "5m": ("minute", 5),
    "15m": ("minute", 15),
    "1h": ("hour", 1),
    "4h": ("hour", 4),
    "1d": ("day", 1),
}
"""The company's interval names against the vendor's timeframe and aggregate."""

_LIMIT = 1000
"""Candles per request. The vendor caps a request there; a token older than
a thousand hours is recorded from its last thousand."""


def split_key(symbol: str) -> tuple[str, str]:
    """``<network>:<address>`` into its parts, refusing anything else."""
    network, sep, address = symbol.partition(":")
    if not sep or not network or not address:
        raise IntegrityViolation(f"{symbol!r} is not a token key of the form network:address")
    return network, address


MIN_LIQUIDITY_USD = Decimal(20_000)
"""Below this a token cannot absorb the desk's material size ($5,000) without
the paper fill being a fiction."""

MAX_LIQUIDITY_USD = Decimal(5_000_000)
"""Above this a token is not a memecoin about to be found: wrapped ether and
the majors trend too, and a pool with five million dollars in it is not
where the hypothesis lives. The first dry run's most liquid followed token
was wrapped ether on Base."""


@dataclass(frozen=True, slots=True)
class DexRule:
    """How the followed tokens are chosen. Printed on the grant."""

    networks: tuple[str, ...] = ("solana", "base")
    top: int = 20
    days: int = 7
    min_liquidity_usd: Decimal = MIN_LIQUIDITY_USD
    max_liquidity_usd: Decimal = MAX_LIQUIDITY_USD

    def describe(self) -> str:
        return (
            f"follow up to {self.top} tokens on {', '.join(self.networks)} that the "
            f"attention sources named in the last {self.days} days, with pool liquidity "
            f"between ${self.min_liquidity_usd:,.0f} and ${self.max_liquidity_usd:,.0f}, "
            "newest attention first"
        )

    @classmethod
    def parse(cls, text: str | None, networks: tuple[str, ...]) -> DexRule:
        """The rule back from its own description, so a grant reads as it was
        written even if the defaults move later."""
        rule = cls(networks=networks)
        if not text:
            return rule
        match = re.search(r"follow up to (\d+) tokens .* in the last (\d+) days", text)
        if match is None:
            return rule
        band = re.search(r"between \$([\d,]+) and \$([\d,]+)", text)
        low = Decimal(band.group(1).replace(",", "")) if band else MIN_LIQUIDITY_USD
        high = Decimal(band.group(2).replace(",", "")) if band else MAX_LIQUIDITY_USD
        return cls(
            networks=networks,
            top=int(match.group(1)),
            days=int(match.group(2)),
            min_liquidity_usd=low,
            max_liquidity_usd=high,
        )


_POOL_CACHE: dict[str, str] = {}
"""Token key to the pool its bars are read from, resolved once per process
and again whenever a read fails. The pool is on the snapshot's endpoint."""


@dataclass(frozen=True, slots=True)
class GeckoTerminalCandles:
    """A token's pool OHLCV on GeckoTerminal's public API. No credential.

    The symbol is the token key; the pool is the deepest one the vendor lists
    for the token, resolved on first use. The endpoint recorded on the
    snapshot names the vendor; the pool travels in the ledger payload.
    """

    name: str = "geckoterminal"
    endpoint: str = "https://api.geckoterminal.com/api/v2"
    timeout: int = 25
    pause: float = 2.1
    """Seconds between requests: the vendor allows thirty a minute."""

    opener: Any = None

    def pool_for(self, symbol: str) -> str:
        """The deepest pool the vendor lists for the token, cached."""
        cached = _POOL_CACHE.get(symbol)
        if cached:
            return cached
        network, address = split_key(symbol)
        data = self._get(f"{self.endpoint}/networks/{network}/tokens/{address}/pools?page=1")
        pools = data.get("data", []) if isinstance(data, dict) else []
        best: tuple[Decimal, str] | None = None
        for item in pools:
            attributes = item.get("attributes") or {}
            try:
                reserve = Decimal(str(attributes.get("reserve_in_usd") or "0"))
            except InvalidOperation:
                continue
            pool = str(attributes.get("address", ""))
            if pool and (best is None or reserve > best[0]):
                best = (reserve, pool)
        if best is None:
            raise FeedUnavailable(f"{self.name} lists no pool for {symbol}")
        _POOL_CACHE[symbol] = best[1]
        return best[1]

    def candles(self, symbol: str, *, interval: str, bars: int) -> list[Bar]:
        if bars < 1:
            raise IntegrityViolation("a snapshot needs at least one bar")
        if interval not in _TIMEFRAMES:
            raise IntegrityViolation(
                f"{self.name} has no timeframe for {interval!r}; one of {list(_TIMEFRAMES)}"
            )
        timeframe, aggregate = _TIMEFRAMES[interval]
        network, _ = split_key(symbol)
        pool = self.pool_for(symbol)
        url = (
            f"{self.endpoint}/networks/{network}/pools/{pool}/ohlcv/{timeframe}"
            f"?aggregate={aggregate}&limit={min(bars, _LIMIT)}&currency=usd"
        )
        try:
            data = self._get(url)
        except FeedUnavailable:
            _POOL_CACHE.pop(symbol, None)  # the pool may have drained; resolve again next time
            raise
        rows = (
            ((data.get("data") or {}).get("attributes") or {}).get("ohlcv_list")
            if isinstance(data, dict)
            else None
        )
        if not isinstance(rows, list) or not rows:
            raise FeedUnavailable(f"{self.name} returned no candles for {symbol} at {interval}")
        collected: dict[int, Bar] = {}
        for row in rows:
            bar = _bar_from(row)
            collected[int(bar.timestamp.timestamp())] = bar
        ordered = [collected[key] for key in sorted(collected)]
        return ordered[-bars:]

    def _get(self, url: str) -> Any:
        """One request, paced: the pause before every call keeps a wake of
        twenty tokens (a pool lookup and a candle read each) under the
        vendor's thirty a minute, and a 429 is waited out once. The first
        dry run paced only the candle reads and was refused on six of eight
        tokens."""
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        opener = self.opener or urllib.request.urlopen
        for attempt in range(2):
            if self.pause:
                time.sleep(self.pause if attempt == 0 else self.pause * 10)
            try:
                with opener(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code == 429 and attempt == 0:
                    continue
                raise FeedUnavailable(f"{self.name} refused the request ({error.code})") from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise FeedUnavailable(f"{self.name} could not be reached: {error}") from error
            except ValueError as error:
                raise FeedUnavailable(
                    f"{self.name} answered with something that is not JSON"
                ) from error
        raise FeedUnavailable(f"{self.name} refused the request (429) twice")


def _bar_from(row: list[Any]) -> Bar:
    """``[time, open, high, low, close, volume]``, time in seconds."""
    if len(row) < 6:
        raise FeedUnavailable(f"a candle row has {len(row)} fields, not 6")
    try:
        values = [Decimal(str(v)) for v in row[1:6]]
    except InvalidOperation as error:
        raise FeedUnavailable(f"a candle row is not numeric: {row}") from error
    return Bar(
        timestamp=dt.datetime.fromtimestamp(int(row[0]), tz=dt.UTC),
        open=values[0],
        high=values[1],
        low=values[2],
        close=values[3],
        volume=values[4],
    )


def followed_tokens(
    session: Session, *, rule: DexRule, at: dt.datetime
) -> list[tuple[str, Decimal]]:
    """The tokens the rule follows now: keyed, with the liquidity that qualified them.

    A token qualifies by an attention event on one of the rule's networks
    inside the window whose liquidity (a boost's pair liquidity, a trending
    pool's reserve) lies inside the rule's band; the newest attention comes
    first. The list is what the wake records bars for. Deterministic and in
    software.
    """
    since = at - dt.timedelta(days=rule.days)
    rows = session.execute(
        sa.select(WorldEvent)
        .where(
            WorldEvent.kind.in_(ATTENTION_KINDS),
            WorldEvent.entity_kind == "instrument",
            WorldEvent.at >= since,
        )
        .order_by(WorldEvent.at.desc())
    ).scalars()
    seen: dict[str, Decimal] = {}
    judged: set[str] = set()
    for event in rows:  # newest first
        key = str(event.entity_key)
        if key in judged:
            continue
        judged.add(key)
        network, _, _ = key.partition(":")
        if network not in rule.networks:
            continue
        payload = event.payload or {}
        raw = payload.get("liquidity_usd") or payload.get("reserve_usd") or "0"
        try:
            liquidity = Decimal(str(raw))
        except InvalidOperation:
            continue
        if not rule.min_liquidity_usd <= liquidity <= rule.max_liquidity_usd:
            continue
        seen[key] = liquidity
        if len(seen) >= rule.top:
            break
    return list(seen.items())


def names_of(session: Session, symbols: tuple[str, ...]) -> dict[str, str]:
    """Each token key's ticker symbol, from the entity the attention source
    saw, for the readers that search by cashtag. A key with no name is left
    out, and such a reader skips it."""
    if not symbols:
        return {}
    rows = session.execute(
        sa.select(Entity).where(Entity.kind == "instrument", Entity.key.in_(symbols))
    ).scalars()
    out: dict[str, str] = {}
    for entity in rows:
        symbol = str((entity.attributes or {}).get("symbol") or entity.name or "").strip()
        if symbol and ":" in entity.key:
            out[str(entity.key)] = symbol
    return out
