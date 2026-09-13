"""M43 — sources for every market, chosen by the agents, keyed by a person.

The acceptance criteria, each with a test named after it:

* the catalogue names, for every source, the markets it bears on and the key
  it needs, and a keyed source is unavailable until a person supplies the
  key in the environment,
* an agent is shown the catalogue by market with the instruments the company
  follows on each desk, may ask for a keyed source, and the wake says which
  key is missing until it is there,
* a social post naming an instrument is ``social.post`` at its own time with
  the poster's own tag, and a burst derives with its threshold,
* a Bluesky search result is recorded the same way, and the query is the
  cashtag, or the name for a ticker that is a word,
* a paid boost is ``attention.boost`` on the token, an instrument keyed by
  chain and contract, once per total paid, with its symbol and liquidity,
* a pool entering the trending list is ``dex.trending`` on its token, once a
  day,
* a keyed source reads through its official endpoint with the supplied key,
  and the key is never written down,
* the service reads every kind the agents asked for under the one grant,
  with one incident per failing source,
* the CLI lists keys by name and whether each is set, never a value.

**Nothing here touches the network.** Every reader takes an opener.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from typer.testing import CliRunner

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.bursts import BURST_MIN
from aurelis.intel.live import CoinbaseCandles, FeedUnavailable
from aurelis.intel.news import CATALOGUE, RssFeed
from aurelis.intel.onchain import (
    DexScreenerBoosts,
    GeckoTerminalTrending,
    fetch_boosts,
    fetch_trending,
    record_boosts,
    record_trending,
    token_key,
)
from aurelis.intel.social import (
    BlueskySearch,
    RedditListing,
    StocktwitsStream,
    bluesky_query,
    record_posts,
    stocktwits_symbol,
)
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once
from aurelis.sources.catalogue import KEY_PREFIX, KINDS, key_status, markets_of
from aurelis.sources.seat import request_sources
from aurelis.world.store import World
from aurelis.world.tables import Entity, WorldEvent

_HOUR = 3600
_START = 1_780_000_000
_NOW = dt.datetime.fromtimestamp(_START + 200 * _HOUR, tz=dt.UTC)
_REDDIT_ID = f"{KEY_PREFIX}REDDIT_CLIENT_ID"
_REDDIT_SECRET = f"{KEY_PREFIX}REDDIT_CLIENT_SECRET"


# ------------------------------------------------------------ fixtures


class _Route:
    """An opener that answers by URL, records what it was asked, and can fail."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: int = 0) -> Any:  # noqa: ARG002
        self.requests.append(request)
        for prefix, answer in self.routes.items():
            if request.full_url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                body = answer(request) if callable(answer) else answer
                return io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())
        raise OSError(f"no route for {request.full_url}")


def _stocktwits(count: int, *, symbol: str = "BTC.X", since: dt.datetime = _NOW) -> dict[str, Any]:
    return {
        "symbol": {"symbol": symbol},
        "messages": [
            {
                "id": 700_000 + i,
                "body": f"${symbol.split('.')[0]} message {i}",
                "created_at": (since - dt.timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "user": {"username": f"trader{i}"},
                "entities": {"sentiment": {"basic": "Bullish"} if i % 2 == 0 else None},
                "likes": {"total": i},
            }
            for i in range(count)
        ],
    }


def _bluesky(count: int, *, since: dt.datetime = _NOW) -> dict[str, Any]:
    return {
        "posts": [
            {
                "uri": f"at://did:plc:x/app.bsky.feed.post/3k{i}",
                "author": {"handle": f"poster{i}.bsky.social"},
                "record": {
                    "text": f"$BTC post {i}",
                    "createdAt": (since - dt.timedelta(minutes=7 * i)).isoformat(),
                },
                "likeCount": 10 + i,
                "repostCount": i,
                "indexedAt": since.isoformat(),
            }
            for i in range(count)
        ]
    }


def _boost(chain: str, address: str, total: str, *, amount: str | None = "100") -> dict[str, Any]:
    out = {
        "url": f"https://dexscreener.com/{chain}/{address}",
        "chainId": chain,
        "tokenAddress": address,
        "totalAmount": total,
        "description": "to the moon",
    }
    if amount is not None:
        out["amount"] = amount
    return out


def _pair(chain: str, address: str, symbol: str, liquidity: float) -> dict[str, Any]:
    return {
        "chainId": chain,
        "dexId": "raydium",
        "pairAddress": f"pair-{address}",
        "baseToken": {"address": address, "name": f"{symbol} coin", "symbol": symbol},
        "priceUsd": "0.0012",
        "liquidity": {"usd": liquidity},
        "marketCap": 1_200_000,
        "volume": {"h24": 350_000.5},
        "priceChange": {"h24": 42.5},
        "pairCreatedAt": 1789137705000,
    }


def _trending(network: str, pools: list[tuple[str, str, str]]) -> dict[str, Any]:
    return {
        "data": [
            {
                "id": f"{network}_{pool}",
                "type": "pool",
                "attributes": {
                    "address": pool,
                    "name": f"{symbol} / SOL",
                    "base_token_price_usd": "0.04",
                    "reserve_in_usd": "1197279.23",
                    "market_cap_usd": "43097403.6",
                    "volume_usd": {"h24": "5885569.85"},
                    "price_change_percentage": {"h24": "134.8"},
                    "pool_created_at": "2026-09-09T23:09:57Z",
                },
                "relationships": {"base_token": {"data": {"id": f"{network}_{token}"}}},
            }
            for pool, token, symbol in pools
        ]
    }


def _rss(titles: list[tuple[str, dt.datetime]]) -> bytes:
    items = "".join(
        f"<item><title>{t}</title><link>https://t.test/{i}</link>"
        f"<pubDate>{when.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
        for i, (t, when) in enumerate(titles)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'.encode()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(_NOW)


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    rows = [[_START + i * _HOUR, 99.0, 101.0, 100.0, 100.0 + i, 5.0] for i in range(201)]

    class _Bars:
        def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
            return io.BytesIO(json.dumps(list(reversed(rows))).encode())

    with built.database.session() as session:
        for symbol in ("BTC-USD", "ETH-USD"):
            built.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Bars(), pause=0),
                desk="crypto",
                symbol=symbol,
                bars=201,
            )
    try:
        yield built
    finally:
        built.close()


def _grant(company: Runtime, source: str, *, instruments: tuple[str, ...] = ("BTC-USD",)) -> Any:
    with company.database.session() as session:
        return company.grants.grant(
            session,
            source=source,
            desk="crypto",
            instruments=instruments,
            granted_by="test",
            reason="a test grant, so the service has something to read",
        )


class _Direct:
    """A provider that answers with one text and keeps the prompt it was shown."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.prompts: list[str] = []
        self.name = "mock"

    def complete(self, session: Any, request: LlmRequest) -> Any:  # noqa: ARG002
        self.prompts.append(request.messages[-1].content)
        return MockProvider(responder=lambda _r: self._text).complete(request)


def _events(company: Runtime, kind: str, *, entity_kind: str = "instrument") -> list[WorldEvent]:
    with company.database.session() as session:
        return list(
            session.execute(
                sa.select(WorldEvent)
                .where(WorldEvent.kind == kind, WorldEvent.entity_kind == entity_kind)
                .order_by(WorldEvent.at)
            ).scalars()
        )


# ------------------------------------------------------------ the catalogue


def test_the_catalogue_names_each_sources_markets_and_key_and_a_keyed_source_is_unavailable_until_a_person_supplies_it(  # noqa: E501
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert set(markets_of()) == {
        "crypto",
        "memecoin",
        "equities",
        "options",
        "futures",
        "commodities",
        "fx",
    }, "every desk has at least one source it could read"
    assert all(s.cost == "free" and s.kind in KINDS for s in CATALOGUE.values())
    assert all(s.markets for s in CATALOGUE.values())
    assert CATALOGUE["stocktwits"].keyless and CATALOGUE["stocktwits"].available
    monkeypatch.delenv(_REDDIT_ID, raising=False)
    monkeypatch.delenv(_REDDIT_SECRET, raising=False)
    reddit = CATALOGUE["reddit_memecoins"]
    assert not reddit.keyless and not reddit.available
    assert _REDDIT_ID in reddit.key and "not supplied" in reddit.key
    assert reddit.describe()["markets"] == "memecoin"
    assert {"source": "reddit_memecoins", "variable": _REDDIT_ID, "set": "no"} in key_status()
    monkeypatch.setenv(_REDDIT_ID, "id-123")
    monkeypatch.setenv(_REDDIT_SECRET, "s3cret")
    assert reddit.available and reddit.key == "supplied by a person"
    assert {"source": "reddit_memecoins", "variable": _REDDIT_ID, "set": "yes"} in key_status()
    assert "id-123" not in str(key_status()) and "s3cret" not in str(reddit.describe())


# ------------------------------------------------------------ the seat and the wake


def test_an_agent_is_shown_the_catalogue_by_market_and_may_ask_for_a_keyed_source_and_the_wake_says_which_key_is_missing(  # noqa: E501
    company: Runtime, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_REDDIT_ID, raising=False)
    monkeypatch.delenv(_REDDIT_SECRET, raising=False)
    _grant(company, "coinbase", instruments=("BTC-USD", "ETH-USD"))
    _grant(company, "news", instruments=("BTC-USD", "ETH-USD"))
    provider = _Direct(
        "SOURCES: reddit_memecoins, stocktwits\n"
        "BECAUSE: memecoin attention forms on reddit, and the stream carries the crowd's tag.\n"
    )
    with company.database.session() as session:
        rows = request_sources(
            provider,
            session,
            agent_ref=company.roster.by_handle(session, "INTEL").ref,
            instruments=("BTC-USD", "ETH-USD"),
            desks={"BTC-USD": "crypto", "ETH-USD": "crypto"},
            ledger=company.ledger,
            clock=clock,
        )
    shown = provider.prompts[0]
    assert "markets: memecoin" in shown and "markets: crypto, memecoin" in shown
    assert "crypto: BTC-USD, ETH-USD" in shown, "instruments are shown per desk"
    assert "not supplied" in shown, "the agent sees which sources wait on a person"
    assert [r.source for r in rows] == ["reddit_memecoins", "stocktwits"]

    feeds: dict[str, Any] = {
        "stocktwits": StocktwitsStream(
            CATALOGUE["stocktwits"],
            opener=_Route(
                {
                    "https://api.stocktwits.com/api/2/streams/symbol/BTC.X": _stocktwits(3),
                    "https://api.stocktwits.com/api/2/streams/symbol/ETH.X": _stocktwits(
                        2, symbol="ETH.X"
                    ),
                }
            ),
        )
    }
    service = Service(company, news=lambda name: feeds[name], cycles_per_wake=1, calls_per_day=0)
    wake = cycle_once(company, service=service)
    assert "sources: 1 read" in wake.note and "5 event(s)" in wake.note
    assert f"reddit_memecoins: not read, needs {_REDDIT_ID}" in wake.note
    assert wake.incidents == (), "a missing key is a note for a person, not an incident"
    assert len(_events(company, "social.post")) == 5


# ------------------------------------------------------------ social


def test_a_social_post_naming_an_instrument_is_an_event_at_its_own_time_with_the_posters_tag_and_a_burst_derives(  # noqa: E501
    company: Runtime, clock: FrozenClock
) -> None:
    assert stocktwits_symbol("BTC-USD") == "BTC.X" and stocktwits_symbol("aapl") == "AAPL"
    payload = _stocktwits(BURST_MIN + 2)
    payload["messages"].append(  # a rate needs history: one post two days ago
        {
            "id": 1,
            "body": "$BTC long ago",
            "created_at": (_NOW - dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "user": {"username": "old"},
            "entities": {"sentiment": None},
            "likes": {"total": 0},
        }
    )
    route = _Route({"https://api.stocktwits.com/": payload})
    stream = StocktwitsStream(CATALOGUE["stocktwits"], opener=route)
    posts = stream.posts("BTC.X")
    assert (
        len(posts) == BURST_MIN + 3 and posts[0].sentiment == "bullish" and posts[1].sentiment == ""
    )
    with company.database.session() as session:
        new, bursts = record_posts(
            session,
            company.world,
            company.artifacts,
            source=CATALOGUE["stocktwits"],
            posts=posts,
            instruments=("BTC-USD",),
            clock=clock,
            on="BTC-USD",
        )
        again, _ = record_posts(
            session,
            company.world,
            company.artifacts,
            source=CATALOGUE["stocktwits"],
            posts=posts,
            instruments=("BTC-USD",),
            clock=clock,
            on="BTC-USD",
        )
    assert new == BURST_MIN + 3 and bursts == 1 and again == 0, "the same post twice is one event"
    events = _events(company, "social.post")
    assert (
        events[-1].at.replace(tzinfo=dt.UTC) == _NOW
        and events[-1].payload["sentiment"] == "bullish"
    )
    assert (
        events[-1].payload["source"] == "stocktwits" and events[-1].payload["author"] == "trader0"
    )
    burst = _events(company, "social.burst")[0]
    assert (
        burst.payload["mentions_6h"] == BURST_MIN + 2
        and "trailing week" in burst.payload["threshold"]
    )


def test_a_bluesky_search_result_is_recorded_the_same_way_and_the_query_is_the_cashtag_or_the_name(
    company: Runtime, clock: FrozenClock
) -> None:
    assert bluesky_query("BTC-USD") == "$BTC"
    assert bluesky_query("PUMP-USD") == '"pump.fun"', "a ticker that is a word searches by name"
    route = _Route({"https://api.bsky.app/xrpc/app.bsky.feed.searchPosts": _bluesky(3)})
    search = BlueskySearch(CATALOGUE["bluesky"], opener=route)
    posts = search.posts(bluesky_query("BTC-USD"))
    assert "q=%24BTC" in route.requests[0].full_url and "sort=latest" in route.requests[0].full_url
    assert len(posts) == 3 and posts[0].likes == 10 and posts[0].url.startswith("https://bsky.app/")
    with company.database.session() as session:
        new, _ = record_posts(
            session,
            company.world,
            company.artifacts,
            source=CATALOGUE["bluesky"],
            posts=posts,
            instruments=("BTC-USD",),
            clock=clock,
            on="BTC-USD",
        )
    assert new == 3
    assert {e.payload["source"] for e in _events(company, "social.post")} == {"bluesky"}


# ------------------------------------------------------------ on-chain attention


def test_a_paid_boost_is_an_event_on_the_token_once_per_total_with_the_tokens_symbol_and_liquidity(
    company: Runtime, clock: FrozenClock
) -> None:
    latest = [_boost("solana", "AAA", "100"), _boost("solana", "BBB", "40")]
    top = [_boost("solana", "AAA", "100", amount=None), _boost("bsc", "CCC", "500", amount=None)]
    route = _Route(
        {
            "https://api.dexscreener.com/token-boosts/latest/v1": latest,
            "https://api.dexscreener.com/token-boosts/top/v1": top,
            "https://api.dexscreener.com/tokens/v1/solana/": [
                _pair("solana", "AAA", "WIF", 50_000.0),
                _pair("solana", "AAA", "WIF", 90_000.0),
                _pair("solana", "BBB", "BONK", 10_000.0),
            ],
            "https://api.dexscreener.com/tokens/v1/bsc/": [_pair("bsc", "CCC", "CAKE", 7.5)],
        }
    )
    feed = DexScreenerBoosts(CATALOGUE["dexscreener_boosts"], opener=route)
    fetched = fetch_boosts(feed)
    assert fetched.pairs[token_key("solana", "AAA")].liquidity_usd == "90000.00", "the deepest pair"
    with company.database.session() as session:
        new, _ = record_boosts(
            session,
            company.world,
            company.artifacts,
            source=feed.source,
            fetched=fetched,
            clock=clock,
        )
        again, _ = record_boosts(
            session,
            company.world,
            company.artifacts,
            source=feed.source,
            fetched=fetched,
            clock=clock,
        )
        entity = session.execute(
            sa.select(Entity).where(Entity.kind == "instrument", Entity.key == "solana:AAA")
        ).scalar_one()
    assert new == 3 and again == 0, "AAA in both lists at one total is one event"
    assert entity.name == "WIF" and entity.attributes["symbol"] == "WIF"
    boosts = _events(company, "attention.boost", entity_kind="instrument")
    aaa = next(e for e in boosts if e.entity_key == "solana:AAA")
    assert aaa.payload["symbol"] == "WIF" and aaa.payload["liquidity_usd"] == "90000.00"
    assert aaa.payload["total_boosts"] == "100" and aaa.payload["market_cap"] == "1200000.00"
    # A further boost raises the total: a new event on the same token.
    route.routes["https://api.dexscreener.com/token-boosts/latest/v1"] = [
        _boost("solana", "AAA", "150")
    ]
    with company.database.session() as session:
        more, _ = record_boosts(
            session,
            company.world,
            company.artifacts,
            source=feed.source,
            fetched=fetch_boosts(feed),
            clock=clock,
        )
    assert more == 1


def test_a_pool_entering_the_trending_list_is_an_event_on_its_token_once_a_day(
    company: Runtime, clock: FrozenClock
) -> None:
    route = _Route(
        {
            "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools": _trending(
                "solana", [("pool1", "tokA", "EMBER"), ("pool2", "tokB", "MOG")]
            ),
            "https://api.geckoterminal.com/api/v2/networks/base/trending_pools": _trending(
                "base", [("pool3", "tokC", "BRETT")]
            ),
            "https://api.geckoterminal.com/api/v2/networks/eth/trending_pools": _trending(
                "eth", []
            ),
            "https://api.geckoterminal.com/api/v2/networks/bsc/trending_pools": _trending(
                "bsc", []
            ),
        }
    )
    feed = GeckoTerminalTrending(CATALOGUE["geckoterminal_trending"], opener=route)
    fetched = fetch_trending(feed)
    assert set(fetched) == {"solana", "base", "eth", "bsc"} and fetched["solana"][0].rank == 1
    with company.database.session() as session:
        new, _ = record_trending(
            session,
            company.world,
            company.artifacts,
            source=feed.source,
            fetched=fetched,
            clock=clock,
        )
        again, _ = record_trending(
            session,
            company.world,
            company.artifacts,
            source=feed.source,
            fetched=fetched,
            clock=clock,
        )
    assert new == 3 and again == 0
    clock.advance(hours=25)
    with company.database.session() as session:
        later, _ = record_trending(
            session,
            company.world,
            company.artifacts,
            source=feed.source,
            fetched=fetched,
            clock=clock,
        )
    assert later == 3, "still trending a day later is a new event"
    trending = _events(company, "dex.trending", entity_kind="instrument")
    first = next(e for e in trending if e.entity_key == "solana:tokA")
    assert first.payload["symbol"] == "EMBER" and first.payload["volume_h24"] == "5885569.85"


# ------------------------------------------------------------ keyed sources


def test_a_keyed_source_reads_with_the_supplied_key_and_the_key_is_never_written_down(
    company: Runtime, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_REDDIT_ID, raising=False)
    monkeypatch.delenv(_REDDIT_SECRET, raising=False)
    listing = {
        "data": {
            "children": [
                {
                    "data": {
                        "name": "t3_abc",
                        "title": "Bitcoin to the moon",
                        "selftext": "BTC is unstoppable",
                        "created_utc": (_NOW - dt.timedelta(minutes=30)).timestamp(),
                        "author": "u1",
                        "permalink": "/r/CryptoCurrency/comments/abc/",
                        "score": 12,
                        "num_comments": 3,
                        "subreddit": "CryptoCurrency",
                    }
                },
                {
                    "data": {
                        "name": "t3_def",
                        "title": "A post about nothing the company follows",
                        "selftext": "",
                        "created_utc": (_NOW - dt.timedelta(minutes=10)).timestamp(),
                        "author": "u2",
                        "permalink": "/r/CryptoMarkets/comments/def/",
                        "score": 1,
                        "num_comments": 0,
                        "subreddit": "CryptoMarkets",
                    }
                },
            ]
        }
    }

    def token(request: Any) -> bytes:
        assert request.get_method() == "POST"
        assert request.get_header("Authorization", "").startswith("Basic ")
        return json.dumps({"access_token": "tok-xyz", "token_type": "bearer"}).encode()

    def posts(request: Any) -> bytes:
        assert request.get_header("Authorization") == "Bearer tok-xyz"
        return json.dumps(listing).encode()

    route = _Route(
        {
            "https://www.reddit.com/api/v1/access_token": token,
            "https://oauth.reddit.com/r/CryptoCurrency+CryptoMarkets/new": posts,
        }
    )
    reader = RedditListing(CATALOGUE["reddit_crypto"], opener=route)
    with pytest.raises(FeedUnavailable, match=_REDDIT_ID):
        reader.posts()
    monkeypatch.setenv(_REDDIT_ID, "client-id-value")
    monkeypatch.setenv(_REDDIT_SECRET, "client-secret-value")
    fetched = reader.posts()
    assert [p.venue for p in fetched] == ["CryptoCurrency", "CryptoMarkets"]
    with company.database.session() as session:
        new, _ = record_posts(
            session,
            company.world,
            company.artifacts,
            source=reader.source,
            posts=fetched,
            instruments=("BTC-USD", "ETH-USD"),
            clock=clock,
        )
    assert new == 1, "only the post that names a followed instrument"
    with company.database.session() as session:
        dumped = " ".join(
            str(row)
            for table in ("world_events", "artifacts", "events", "entities")
            for row in session.execute(sa.text(f"SELECT * FROM {table}")).all()
        )
    assert "client-id-value" not in dumped and "client-secret-value" not in dumped
    assert "tok-xyz" not in dumped


# ------------------------------------------------------------ the service


def test_the_service_reads_every_kind_the_agents_asked_for_under_the_one_grant_with_one_incident_per_failing_source(  # noqa: E501
    company: Runtime, clock: FrozenClock
) -> None:
    _grant(company, "news", instruments=("BTC-USD",))
    with company.database.session() as session:
        request_sources(
            _Direct(
                "SOURCES: coindesk, stocktwits, dexscreener_boosts, geckoterminal_trending\n"
                "BECAUSE: headlines, the crowd's tag, and where memecoin attention starts.\n"
            ),
            session,
            agent_ref=company.roster.by_handle(session, "INTEL").ref,
            instruments=("BTC-USD",),
            ledger=company.ledger,
            clock=clock,
        )
    feeds: dict[str, Any] = {
        "coindesk": RssFeed(
            CATALOGUE["coindesk"],
            opener=_Route(
                {"https://": _rss([("Bitcoin ETF inflows", _NOW - dt.timedelta(hours=1))])}
            ),
        ),
        "stocktwits": StocktwitsStream(
            CATALOGUE["stocktwits"], opener=_Route({"https://": _stocktwits(2)})
        ),
        "dexscreener_boosts": DexScreenerBoosts(
            CATALOGUE["dexscreener_boosts"],
            opener=_Route(
                {
                    "https://api.dexscreener.com/token-boosts/latest/v1": [
                        _boost("solana", "AAA", "10")
                    ],
                    "https://api.dexscreener.com/token-boosts/top/v1": [],
                    "https://api.dexscreener.com/tokens/v1/solana/": [
                        _pair("solana", "AAA", "WIF", 1.0)
                    ],
                }
            ),
        ),
        "geckoterminal_trending": GeckoTerminalTrending(
            CATALOGUE["geckoterminal_trending"], opener=_Route({"https://": OSError("down")})
        ),
    }
    service = Service(company, news=lambda name: feeds[name], cycles_per_wake=1, calls_per_day=0)
    wake = cycle_once(company, service=service)
    assert "sources: 3 read" in wake.note and "4 event(s)" in wake.note, wake.note
    assert len(wake.incidents) == 1
    with company.database.session() as session:
        subject = session.execute(
            sa.text("SELECT subject FROM alerts WHERE ref = :r"), {"r": wake.incidents[0]}
        ).scalar_one()
    assert subject.endswith(":geckoterminal_trending")
    assert len(_events(company, "news.mention")) == 1
    assert len(_events(company, "social.post")) == 2
    assert len(_events(company, "attention.boost", entity_kind="instrument")) == 1
    with company.database.session() as session:
        lines = World.events_for(
            session, entity_kind="instrument", entity_key="solana:AAA", limit=5
        )
    assert lines and lines[0].payload["symbol"] == "WIF"
    assert Decimal(lines[0].payload["liquidity_usd"]) == Decimal("1.00")


def test_a_source_that_fails_on_one_instrument_still_records_the_others_and_the_wake_names_it(
    company: Runtime, clock: FrozenClock
) -> None:
    _grant(company, "news", instruments=("BTC-USD", "ETH-USD", "LIGHTER-USD"))
    with company.database.session() as session:
        request_sources(
            _Direct(
                "SOURCES: stocktwits"
                + chr(10)
                + "BECAUSE: the stream carries the crowd's own tag."
                + chr(10)
            ),
            session,
            agent_ref=company.roster.by_handle(session, "INTEL").ref,
            instruments=("BTC-USD", "ETH-USD", "LIGHTER-USD"),
            ledger=company.ledger,
            clock=clock,
        )
    import urllib.error

    route = _Route(
        {
            "https://api.stocktwits.com/api/2/streams/symbol/BTC.X": _stocktwits(2),
            "https://api.stocktwits.com/api/2/streams/symbol/ETH.X": _stocktwits(1, symbol="ETH.X"),
            "https://api.stocktwits.com/api/2/streams/symbol/LIGHTER.X": urllib.error.HTTPError(
                "https://api.stocktwits.com/",
                404,
                "Not Found",
                {},
                None,  # type: ignore[arg-type]
            ),
        }
    )
    feeds = {"stocktwits": StocktwitsStream(CATALOGUE["stocktwits"], opener=route)}
    service = Service(company, news=lambda name: feeds[name], cycles_per_wake=1, calls_per_day=0)
    wake = cycle_once(company, service=service)
    assert wake.incidents == (), "one symbol the platform does not list is not an incident"
    assert "sources: 1 read, 3 event(s)" in wake.note
    assert "stocktwits: 1 of 3 not read (LIGHTER-USD: stocktwits LIGHTER.X refused" in wake.note
    # Every instrument failing is an incident, and nothing is read.
    route.routes["https://api.stocktwits.com/api/2/streams/symbol/BTC.X"] = OSError("down")
    route.routes["https://api.stocktwits.com/api/2/streams/symbol/ETH.X"] = OSError("down")
    down = cycle_once(company, service=service)
    assert len(down.incidents) == 1 and "sources: 0 read" in down.note


# ------------------------------------------------------------ the CLI


def test_the_cli_lists_keys_by_name_and_whether_each_is_set_never_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aurelis.cli.main import app

    monkeypatch.setenv(_REDDIT_ID, "the-id-value")
    monkeypatch.delenv(_REDDIT_SECRET, raising=False)
    result = CliRunner().invoke(app, ["source", "keys"])
    assert result.exit_code == 0, result.output
    assert _REDDIT_ID in result.output and _REDDIT_SECRET in result.output
    assert re.search(r"REDDIT_CLIENT_ID\s+\S*\s*yes", result.output.replace("│", " "))
    assert "the-id-value" not in result.output
    listed = CliRunner().invoke(app, ["source", "catalogue"])
    assert listed.exit_code == 0 and "memecoin" in listed.output and "stocktwits" in listed.output
