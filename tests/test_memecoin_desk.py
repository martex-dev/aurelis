"""M44 — the memecoin desk opens: a price recording per token, followed by rule.

The acceptance criteria, each with a test named after it:

* a token's pool candles are recorded as a snapshot on the memecoin desk,
  keyed by chain and contract, from the deepest pool the vendor lists,
* the following rule names the tokens the attention sources surfaced in its
  window on its networks, most liquid first, capped, and reads back from
  the grant it was printed on,
* a dex grant names networks and a rule, and the wake records bars for the
  followed tokens, derives their price events, and says so,
* a mechanism on a token's attention seals a prediction against the token's
  own close, and a paper trade on it pays the memecoin desk's costs,
* a paper fill pays the costs of the instrument's desk whatever desk the
  version names,
* a social reader searches a followed token by its ticker, not its contract,
  and skips a token it has no name for,
* a mechanism is stated on the desk its pattern fired on, not on a default.

**Nothing here touches the network.** Every reader takes an opener.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.errors import IntegrityViolation
from aurelis.intel.dex import (
    DexRule,
    GeckoTerminalCandles,
    followed_tokens,
    names_of,
    split_key,
)
from aurelis.intel.news import CATALOGUE
from aurelis.intel.social import BlueskySearch
from aurelis.mechanism.paper import trade_firings
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.tables import MechanismTrade
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once
from aurelis.sources.reading import fetch_source
from aurelis.trading.tables import Fill, Order
from aurelis.world.tables import WorldEvent

_HOUR = 3600
_START = 1_780_000_000
_NOW = dt.datetime.fromtimestamp(_START + 300 * _HOUR + 600, tz=dt.UTC)
_TOKEN = "solana:TokenAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_OTHER = "base:0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


class _Route:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    def __call__(self, request: Any, timeout: int = 0) -> Any:  # noqa: ARG002
        self.requests.append(request.full_url)
        for prefix, answer in self.routes.items():
            if request.full_url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                body = answer(request) if callable(answer) else answer
                return io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())
        raise OSError(f"no route for {request.full_url}")


def _pools(*pools: tuple[str, str]) -> dict[str, Any]:
    return {
        "data": [
            {"attributes": {"address": address, "reserve_in_usd": reserve, "name": "X / SOL"}}
            for address, reserve in pools
        ]
    }


def _ohlcv(count: int, *, climb: bool = True) -> dict[str, Any]:
    rows = []
    for i in range(count):
        level = 0.01 + (0.0001 * i if climb else 0.0)
        rows.append([_START + i * _HOUR, level, level * 1.01, level * 0.99, level, 1000.0 + i])
    return {"data": {"attributes": {"ohlcv_list": list(reversed(rows))}}}


def _dex_feed(*, count: int = 300) -> GeckoTerminalCandles:
    network, address = split_key(_TOKEN)
    return GeckoTerminalCandles(
        pause=0,
        opener=_Route(
            {
                f"https://api.geckoterminal.com/api/v2/networks/{network}/tokens/{address}/pools": (
                    _pools(("poolShallow", "1000.5"), ("poolDeep", "250000.75"))
                ),
                "https://api.geckoterminal.com/api/v2/networks/solana/pools/poolDeep/ohlcv/hour": (
                    _ohlcv(count)
                ),
                "https://api.geckoterminal.com/api/v2/networks/base/": _pools(("poolB", "5")),
            }
        ),
    )


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(_NOW)


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _attention(company: Runtime, key: str, *, hours_ago: int, liquidity: str, kind: str) -> None:
    with company.database.session() as session:
        chain, address = split_key(key)
        company.world.see(
            session,
            kind="instrument",
            key=key,
            name="WIF" if key == _TOKEN else "BRETT",
            attributes={
                "chain": chain,
                "address": address,
                "symbol": "WIF" if key == _TOKEN else "BRETT",
            },
            source="test",
            at=company.clock.now(),
        )
        company.world.record(
            session,
            kind=kind,
            at=company.clock.now() - dt.timedelta(hours=hours_ago),
            entity_kind="instrument",
            entity_key=key,
            payload={"symbol": "WIF", "liquidity_usd": liquidity, "total_boosts": str(hours_ago)},
            source="test",
        )


def _dex_grant(company: Runtime, *, networks: tuple[str, ...] = ("solana", "base")) -> Any:
    with company.database.session() as session:
        return company.grants.grant(
            session,
            source="dex",
            desk="memecoin",
            instruments=networks,
            granted_by="test",
            reason="follow what the attention sources surface, for the record",
            rule=DexRule(networks=networks, top=2, days=7).describe(),
        )


# ------------------------------------------------------------ the feed


def test_a_tokens_pool_candles_are_recorded_on_the_memecoin_desk_keyed_by_chain_and_contract(
    company: Runtime,
) -> None:
    feed = _dex_feed(count=300)
    bars = feed.candles(_TOKEN, interval="1h", bars=400)
    assert len(bars) == 300 and bars[0].timestamp < bars[-1].timestamp
    assert feed.pool_for(_TOKEN) == "poolDeep", "the deepest pool, not the first"
    assert any("poolDeep/ohlcv/hour" in url and "limit=400" in url for url in feed.opener.requests)
    with pytest.raises(IntegrityViolation, match="network:address"):
        feed.candles("BTC-USD", interval="1h", bars=10)
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session, feed, desk="memecoin", symbol=_TOKEN, bars=400, at=company.clock.now()
        )
    assert snapshot.desk == "memecoin" and snapshot.symbol == _TOKEN
    assert snapshot.source == "geckoterminal" and snapshot.bars == 300


# ------------------------------------------------------------ the rule


def test_the_following_rule_names_the_tokens_the_attention_sources_surfaced_most_liquid_first(
    company: Runtime,
) -> None:
    _attention(company, _TOKEN, hours_ago=2, liquidity="90000.00", kind="attention.boost")
    _attention(company, _OTHER, hours_ago=30, liquidity="25000.00", kind="dex.trending")
    _attention(company, "eth:0xC", hours_ago=1, liquidity="999999", kind="attention.boost")
    _attention(company, "solana:Stale", hours_ago=24 * 9, liquidity="777", kind="attention.boost")
    _attention(company, "solana:Weth", hours_ago=1, liquidity="120000000", kind="dex.trending")
    _attention(company, "solana:Dust", hours_ago=1, liquidity="900", kind="attention.boost")
    rule = DexRule(networks=("solana", "base"), top=5, days=7)
    with company.database.session() as session:
        followed = followed_tokens(session, rule=rule, at=company.clock.now())
        names = names_of(session, tuple(k for k, _ in followed))
    assert [k for k, _ in followed] == [_TOKEN, _OTHER], (
        "eth is not a followed network; stale is out; wrapped ether and dust are outside the band"
    )
    assert followed[0][1] == Decimal("90000.00")
    assert names == {_TOKEN: "WIF", _OTHER: "BRETT"}
    with company.database.session() as session:
        capped = followed_tokens(
            session, rule=DexRule(("solana", "base"), top=1, days=7), at=company.clock.now()
        )
    assert [k for k, _ in capped] == [_TOKEN]
    text = rule.describe()
    assert "up to 5 tokens" in text and "last 7 days" in text and "$20,000 and $5,000,000" in text
    assert DexRule.parse(text, ("solana",)) == DexRule(("solana",), top=5, days=7)
    narrow = DexRule(("base",), top=3, days=2, min_liquidity_usd=Decimal(1000))
    assert DexRule.parse(narrow.describe(), ("base",)) == narrow
    assert DexRule.parse("something else", ("base",)) == DexRule(("base",))


# ------------------------------------------------------------ the wake


def test_a_dex_grant_names_networks_and_a_rule_and_the_wake_records_the_followed_tokens(
    company: Runtime,
) -> None:
    grant = _dex_grant(company)
    assert grant.is_dex and not grant.is_news and grant.rule and "follow up to 2" in grant.rule
    _attention(company, _TOKEN, hours_ago=2, liquidity="90000.00", kind="attention.boost")
    feed = _dex_feed(count=300)
    service = Service(company, dex=lambda _grant: feed, cycles_per_wake=1, calls_per_day=0)
    wake = cycle_once(company, service=service)
    assert wake.incidents == (), wake.note
    assert "dex: 1 token(s) followed, 1 recorded" in wake.note
    assert len(wake.fetched) == 1
    with company.database.session() as session:
        kinds = {
            k
            for (k,) in session.execute(
                sa.select(WorldEvent.kind).where(WorldEvent.entity_key == _TOKEN)
            )
        }
    assert "attention.boost" in kinds and any(k.startswith("price.") for k in kinds), (
        "the token's price events sit on the same entity as its attention"
    )
    # A token the vendor has no pool for is an incident for that token, not the wake.
    _attention(company, _OTHER, hours_ago=1, liquidity="25000.00", kind="dex.trending")
    again = cycle_once(company, service=service)
    assert "dex: 2 token(s) followed, 1 recorded" in again.note
    assert len(again.incidents) == 1


# ------------------------------------------------------------ a mechanism on attention


def test_a_mechanism_on_a_tokens_attention_seals_against_its_close_and_trades_at_the_desks_costs(
    company: Runtime,
) -> None:
    _dex_grant(company)
    feed = _dex_feed(count=300)
    with company.database.session() as session:
        company.snapshots.ingest(
            session, feed, desk="memecoin", symbol=_TOKEN, bars=400, at=company.clock.now()
        )
    _attention(company, _TOKEN, hours_ago=3, liquidity="90000.00", kind="attention.boost")
    with company.database.session() as session:
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="paid attention then buyers",
            trigger_kind="attention.boost",
            desk="memecoin",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.6"),
            why="a paid boost puts the token on the lists retail buys from.",
            other_side="the promoter, who sells into the attention it paid for.",
            decay="it dies once the lists are known to be paid for, within months.",
            origin="invented",
            found_on_instrument="ZZZ",
            found_on_event="none",
            model="test",
        )
        run = generate_predictions(session, mechanism, clock=company.clock)
        assert len(run.sealed) == 1, run.describe()
        result = trade_firings(company, session, mechanism, at=company.clock.now())
        assert result.opened, result.describe()
        trade = session.execute(
            sa.select(MechanismTrade).where(MechanismTrade.mechanism_ref == mechanism.ref)
        ).scalar_one()
        order = session.execute(
            sa.select(Order).where(Order.ref == trade.open_order_ref)
        ).scalar_one()
        fill = session.execute(sa.select(Fill).where(Fill.order_ref == order.ref)).scalar_one()
        book_desks = session.execute(
            sa.text("SELECT desks FROM portfolios WHERE ref = :r"), {"r": order.portfolio_ref}
        ).scalar_one()
    assert order.symbol == _TOKEN and order.desk == "memecoin" and "memecoin" in str(book_desks)
    notional = Decimal(str(fill.price)) * Decimal(str(fill.quantity))
    paid_bps = Decimal(str(fill.fee)) / notional * 10_000
    assert paid_bps.quantize(Decimal("1")) == Decimal("30"), "the memecoin desk's commission"
    assert Decimal(str(fill.price)) > Decimal(order.expected_price), (
        "the desk's spread and impact move the fill against the buyer"
    )


def test_a_paper_fill_pays_the_costs_of_the_instruments_desk_whatever_desk_the_version_names(
    company: Runtime,
) -> None:
    """A crypto-desk mechanism whose event fired on a token is filled at the
    memecoin desk's costs on that token: the market sets the cost, not the
    book."""
    _dex_grant(company)
    feed = _dex_feed(count=300)
    with company.database.session() as session:
        company.snapshots.ingest(
            session, feed, desk="memecoin", symbol=_TOKEN, bars=400, at=company.clock.now()
        )
    _attention(company, _TOKEN, hours_ago=3, liquidity="90000.00", kind="attention.boost")
    with company.database.session() as session:
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="attention anywhere",
            trigger_kind="attention.boost",
            desk="crypto",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.6"),
            why="a paid boost puts the token on the lists retail buys from.",
            other_side="the promoter, who sells into the attention it paid for.",
            decay="it dies once the lists are known to be paid for, within months.",
            origin="invented",
            found_on_instrument="ZZZ",
            found_on_event="none",
            model="test",
        )
        generate_predictions(session, mechanism, clock=company.clock)
        result = trade_firings(company, session, mechanism, at=company.clock.now())
        assert result.opened, result.describe()
        trade = session.execute(
            sa.select(MechanismTrade).where(MechanismTrade.mechanism_ref == mechanism.ref)
        ).scalar_one()
        order = session.execute(
            sa.select(Order).where(Order.ref == trade.open_order_ref)
        ).scalar_one()
        fill = session.execute(sa.select(Fill).where(Fill.order_ref == order.ref)).scalar_one()
    assert order.desk == "crypto", "the version's desk is the book's"
    notional = Decimal(str(fill.price)) * Decimal(str(fill.quantity))
    paid_bps = Decimal(str(fill.fee)) / notional * 10_000
    assert paid_bps.quantize(Decimal("1")) == Decimal("30"), "but the fill pays the token's desk"


# ------------------------------------------------------------ social by ticker


def test_a_social_reader_searches_a_followed_token_by_its_ticker_and_skips_one_without_a_name() -> (
    None
):
    route = _Route({"https://api.bsky.app/": {"posts": []}})
    feed = BlueskySearch(CATALOGUE["bluesky"], opener=route)
    fetched = fetch_source(
        CATALOGUE["bluesky"], feed, ("BTC-USD", _TOKEN, _OTHER), names={_TOKEN: "WIF"}
    )
    assert set(fetched.posts_on) == {"BTC-USD", _TOKEN}
    assert any("q=%24WIF" in url for url in route.requests)
    assert not any("TokenAAAA" in url for url in route.requests)
    assert _OTHER in fetched.failures and "no ticker" in fetched.failures[_OTHER]


# ------------------------------------------------------------ the desk of a mechanism


def test_a_mechanism_is_stated_on_the_desk_its_pattern_fired_on(company: Runtime) -> None:
    from aurelis.mechanism.discovery import propose_mechanism

    feed = _dex_feed(count=300)
    with company.database.session() as session:
        company.snapshots.ingest(
            session, feed, desk="memecoin", symbol=_TOKEN, bars=400, at=company.clock.now()
        )
    for hours in (30, 20, 10):
        _attention(company, _TOKEN, hours_ago=hours, liquidity="1", kind="attention.boost")
        _attention(company, _TOKEN, hours_ago=hours - 2, liquidity="1", kind="dex.trending")

    def _states(request: Any) -> str:
        if "State a mechanism for this pattern" in request.messages[-1].content:
            return (
                "MECHANISM: boost then trending\nDIRECTION: up\nHORIZON: 6\nCONFIDENCE: 0.6\n"
                "WHY: a paid boost puts the token where the trending list is computed from.\n"
                "OTHER_SIDE: the promoter selling into it.\nDECAY: months, as lists get wise.\n"
            )
        return standins()(request)

    class _Seated:
        name = "mock"

        def complete(self, session: Any, request: Any) -> Any:  # noqa: ARG002
            return MockProvider(responder=_states).complete(request)

    with company.database.session() as session:
        mechanism = propose_mechanism(
            _Seated(),
            session,
            company.mechanisms,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            trigger_kind="attention.boost",
            second_kind="dex.trending",
            desk=None,
            window_hours=24,
            ledger=company.ledger,
        )
    assert mechanism is not None
    assert mechanism.desk == "memecoin" and mechanism.found_on_instrument == _TOKEN
