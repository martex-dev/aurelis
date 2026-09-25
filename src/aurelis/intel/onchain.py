"""Where a memecoin's attention shows first: paid boosts and trending pools.

Two aggregators publish this without a credential. **DEX Screener** lists
the tokens whose promoters just paid to boost them and the most-boosted
tokens, and answers a batch lookup with each token's symbol, liquidity,
market cap and volume. **GeckoTerminal** lists the pools trending on each
network with volume, price change and reserve.

Both are recorded on instrument entities keyed ``<chain>:<address>``: a
token is an instrument on the memecoin desk, named by its contract, and
the key is the one a price recording of the token's pool uses, so the
attention and the price of one token are events on one entity and the
miner can join them. Each is an event rather than a reading: a boost is
recorded once per total paid, a trending pool once per day it enters the
list, so a token boosted again or trending again is a new event and a
token merely still there is not.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock
from aurelis.intel.live import USER_AGENT, FeedUnavailable
from aurelis.sources.catalogue import Source
from aurelis.world.store import World

__all__ = [
    "NETWORKS",
    "Boost",
    "DexScreenerBoosts",
    "GeckoTerminalTrending",
    "Pool",
    "TokenPair",
    "record_boosts",
    "record_trending",
    "token_key",
]

NETWORKS: tuple[str, ...] = ("solana", "base", "eth", "bsc")
"""Where the trending lists are read. Four chains, one request each."""

_TRENDING_ONCE = dt.timedelta(hours=24)
"""A token trending again inside this window is the same event."""


def token_key(chain: str, address: str) -> str:
    return f"{chain}:{address}"


@dataclass(frozen=True, slots=True)
class Boost:
    chain: str
    address: str
    total: Decimal
    amount: Decimal | None
    url: str
    description: str
    top: bool


@dataclass(frozen=True, slots=True)
class TokenPair:
    chain: str
    address: str
    symbol: str
    name: str
    price_usd: str
    liquidity_usd: str
    market_cap: str
    volume_h24: str
    price_change_h24: str
    pair_address: str
    dex: str
    pair_created_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class Pool:
    network: str
    address: str
    name: str
    base_token_address: str
    price_usd: str
    reserve_usd: str
    market_cap_usd: str
    volume_h24: str
    price_change_h24: str
    pool_created_at: dt.datetime | None
    rank: int


def _get_json(opener: Any, url: str, *, timeout: int, name: str) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    fetch = opener or urllib.request.urlopen
    try:
        with fetch(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        raise FeedUnavailable(f"{name} refused the request ({error.code})") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FeedUnavailable(f"{name} could not be reached: {error}") from error
    try:
        return json.loads(payload)
    except ValueError as error:
        raise FeedUnavailable(f"{name} answered with something that is not JSON") from error


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def _money(value: Any) -> str:
    parsed = _dec(value)
    return "" if parsed is None else str(parsed.quantize(Decimal("0.01")))


def _when(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        seconds = float(value) / (1000 if float(value) > 1e11 else 1)
        return dt.datetime.fromtimestamp(seconds, tz=dt.UTC)
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)).astimezone(dt.UTC)


# ------------------------------------------------------------------ DEX Screener

_DEX_TOP = "https://api.dexscreener.com/token-boosts/top/v1"
_DEX_TOKENS = "https://api.dexscreener.com/tokens/v1/{chain}/{addresses}"
_BATCH = 30


@dataclass(frozen=True, slots=True)
class DexScreenerBoosts:
    """The boost lists and the token lookup on the public API. No credential."""

    source: Source
    timeout: int = 25
    opener: Any = None

    @property
    def name(self) -> str:
        return self.source.name

    def _boosts(self, url: str, *, top: bool) -> list[Boost]:
        data = _get_json(self.opener, url, timeout=self.timeout, name=self.name)
        out: list[Boost] = []
        for item in data if isinstance(data, list) else []:
            total = _dec(item.get("totalAmount"))
            if total is None:
                continue
            out.append(
                Boost(
                    chain=str(item.get("chainId", "")),
                    address=str(item.get("tokenAddress", "")),
                    total=total,
                    amount=_dec(item.get("amount")),
                    url=str(item.get("url", "")),
                    description=str(item.get("description", ""))[:200],
                    top=top,
                )
            )
        return out

    def latest(self) -> list[Boost]:
        return self._boosts(self.source.url, top=False)

    def top(self) -> list[Boost]:
        return self._boosts(_DEX_TOP, top=True)

    def tokens(self, chain: str, addresses: list[str]) -> list[TokenPair]:
        """Every pair the aggregator knows for these tokens, thirty at a time."""
        out: list[TokenPair] = []
        for start in range(0, len(addresses), _BATCH):
            batch = addresses[start : start + _BATCH]
            data = _get_json(
                self.opener,
                _DEX_TOKENS.format(chain=chain, addresses=",".join(batch)),
                timeout=self.timeout,
                name=f"{self.name} tokens",
            )
            for pair in data if isinstance(data, list) else []:
                base = pair.get("baseToken") or {}
                out.append(
                    TokenPair(
                        chain=str(pair.get("chainId", chain)),
                        address=str(base.get("address", "")),
                        symbol=str(base.get("symbol", ""))[:32],
                        name=str(base.get("name", ""))[:120],
                        price_usd=str(pair.get("priceUsd", "")),
                        liquidity_usd=_money((pair.get("liquidity") or {}).get("usd")),
                        market_cap=_money(pair.get("marketCap")),
                        volume_h24=_money((pair.get("volume") or {}).get("h24")),
                        price_change_h24=str((pair.get("priceChange") or {}).get("h24", "")),
                        pair_address=str(pair.get("pairAddress", "")),
                        dex=str(pair.get("dexId", "")),
                        pair_created_at=_when(pair.get("pairCreatedAt")),
                    )
                )
        return out


@dataclass(frozen=True, slots=True)
class BoostsFetched:
    boosts: list[Boost]
    pairs: dict[str, TokenPair]
    """The most liquid pair per token key."""


def fetch_boosts(feed: DexScreenerBoosts) -> BoostsFetched:
    """Both lists, then one lookup per chain for the tokens they name."""
    boosts = feed.latest() + feed.top()
    by_chain: dict[str, list[str]] = {}
    for boost in boosts:
        if boost.address not in by_chain.setdefault(boost.chain, []):
            by_chain[boost.chain].append(boost.address)
    pairs: dict[str, TokenPair] = {}
    for chain, addresses in by_chain.items():
        for pair in feed.tokens(chain, addresses):
            key = token_key(pair.chain, pair.address)
            held = pairs.get(key)
            if held is None or (_dec(pair.liquidity_usd) or 0) > (_dec(held.liquidity_usd) or 0):
                pairs[key] = pair
    return BoostsFetched(boosts, pairs)


def record_boosts(
    session: Session,
    world: World,
    artifacts: Any,
    *,
    source: Source,
    fetched: BoostsFetched,
    clock: Clock,
    at: dt.datetime | None = None,
) -> tuple[int, int]:
    """``attention.boost`` on each boosted token, once per total paid.

    Returns ``(events recorded, 0)``: there is no burst here, the boost is
    the burst. The token entity is seen with its symbol and chain, so the
    station and the judges can name it.
    """
    moment = at or clock.now()
    raw = artifacts.put_json(
        session,
        {
            "source": source.name,
            "at": moment.isoformat(),
            "boosts": [
                {"chain": b.chain, "address": b.address, "total": str(b.total), "top": b.top}
                for b in fetched.boosts
            ],
        },
        kind="attention.raw",
        produced_by=source.name,
    )
    new = 0
    seen: set[tuple[str, str]] = set()
    for boost in fetched.boosts:
        key = token_key(boost.chain, boost.address)
        if (key, str(boost.total)) in seen:
            continue
        seen.add((key, str(boost.total)))
        pair = fetched.pairs.get(key)
        world.see(
            session,
            kind="instrument",
            key=key,
            name=pair.symbol if pair else boost.address[:12],
            attributes={
                "chain": boost.chain,
                "address": boost.address,
                "symbol": pair.symbol if pair else "",
                "token_name": pair.name if pair else "",
                "dex": pair.dex if pair else "",
                "pair": pair.pair_address if pair else "",
            },
            source=source.url,
            at=moment,
        )
        earlier = World.events_for(
            session, entity_kind="instrument", entity_key=key, kinds=("attention.boost",), limit=200
        )
        if any(str(e.payload.get("total_boosts")) == str(boost.total) for e in earlier):
            continue
        _, created = world.record(
            session,
            kind="attention.boost",
            at=moment,
            entity_kind="instrument",
            entity_key=key,
            payload={
                "symbol": pair.symbol if pair else "",
                "chain": boost.chain,
                "total_boosts": str(boost.total),
                "amount": str(boost.amount) if boost.amount is not None else "",
                "top": boost.top,
                "price_usd": pair.price_usd if pair else "",
                "liquidity_usd": pair.liquidity_usd if pair else "",
                "market_cap": pair.market_cap if pair else "",
                "volume_h24": pair.volume_h24 if pair else "",
                "price_change_h24": pair.price_change_h24 if pair else "",
                "pair_created_at": (
                    pair.pair_created_at.isoformat() if pair and pair.pair_created_at else ""
                ),
                "url": boost.url[:200],
                "raw": raw.digest[:16],
            },
            source=source.url,
            recorded_at=moment,
        )
        new += int(created)
    return new, 0


# ------------------------------------------------------------------ GeckoTerminal


@dataclass(frozen=True, slots=True)
class GeckoTerminalTrending:
    """``/networks/<network>/trending_pools`` on the public API. No credential."""

    source: Source
    timeout: int = 25
    opener: Any = None

    @property
    def name(self) -> str:
        return self.source.name

    def trending(self, network: str) -> list[Pool]:
        from aurelis.intel.dex import GECKO_PACE
        from aurelis.intel.pacing import pace

        # One vendor, one pace: the token follower reads the same API (M48).
        pace("geckoterminal", 0 if self.opener is not None else GECKO_PACE)
        data = _get_json(
            self.opener,
            self.source.url.format(network=network) + "?page=1",
            timeout=self.timeout,
            name=f"{self.name} {network}",
        )
        out: list[Pool] = []
        for rank, item in enumerate(data.get("data", []) or [], start=1):
            attributes = item.get("attributes") or {}
            base = ((item.get("relationships") or {}).get("base_token") or {}).get("data") or {}
            base_id = str(base.get("id", ""))
            base_address = base_id.split("_", 1)[1] if "_" in base_id else base_id
            out.append(
                Pool(
                    network=network,
                    address=str(attributes.get("address", "")),
                    name=str(attributes.get("name", ""))[:80],
                    base_token_address=base_address,
                    price_usd=str(attributes.get("base_token_price_usd", ""))[:24],
                    reserve_usd=_money(attributes.get("reserve_in_usd")),
                    market_cap_usd=_money(
                        attributes.get("market_cap_usd") or attributes.get("fdv_usd")
                    ),
                    volume_h24=_money((attributes.get("volume_usd") or {}).get("h24")),
                    price_change_h24=str(
                        (attributes.get("price_change_percentage") or {}).get("h24", "")
                    ),
                    pool_created_at=_when(attributes.get("pool_created_at")),
                    rank=rank,
                )
            )
        return out


def fetch_trending(
    feed: GeckoTerminalTrending, networks: tuple[str, ...] = NETWORKS
) -> dict[str, list[Pool]]:
    return {network: feed.trending(network) for network in networks}


def record_trending(
    session: Session,
    world: World,
    artifacts: Any,
    *,
    source: Source,
    fetched: dict[str, list[Pool]],
    clock: Clock,
    at: dt.datetime | None = None,
) -> tuple[int, int]:
    """``dex.trending`` on each trending pool's token, once per day it enters the list."""
    moment = at or clock.now()
    raw = artifacts.put_json(
        session,
        {
            "source": source.name,
            "at": moment.isoformat(),
            "pools": {
                network: [
                    {"pool": p.address, "token": p.base_token_address, "rank": p.rank}
                    for p in pools
                ]
                for network, pools in fetched.items()
            },
        },
        kind="attention.raw",
        produced_by=source.name,
    )
    new = 0
    for network, pools in fetched.items():
        for pool in pools:
            if not pool.base_token_address:
                continue
            key = token_key(network, pool.base_token_address)
            symbol = pool.name.split("/", 1)[0].strip()[:32]
            world.see(
                session,
                kind="instrument",
                key=key,
                name=symbol,
                attributes={
                    "chain": network,
                    "address": pool.base_token_address,
                    "symbol": symbol,
                    "pool": pool.address,
                },
                source=source.url,
                at=moment,
            )
            recent = World.events_for(
                session,
                entity_kind="instrument",
                entity_key=key,
                since=moment - _TRENDING_ONCE,
                kinds=("dex.trending",),
                limit=5,
            )
            if recent:
                continue
            _, created = world.record(
                session,
                kind="dex.trending",
                at=moment,
                entity_kind="instrument",
                entity_key=key,
                payload={
                    "symbol": symbol,
                    "network": network,
                    "pool": pool.address,
                    "rank": pool.rank,
                    "price_usd": pool.price_usd,
                    "reserve_usd": pool.reserve_usd,
                    "market_cap_usd": pool.market_cap_usd,
                    "volume_h24": pool.volume_h24,
                    "price_change_h24": pool.price_change_h24,
                    "pool_created_at": (
                        pool.pool_created_at.isoformat() if pool.pool_created_at else ""
                    ),
                    "raw": raw.digest[:16],
                },
                source=source.url,
                recorded_at=moment,
            )
            new += int(created)
    return new, 0
