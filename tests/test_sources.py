"""M41 — the agents ask for the sources they need.

The acceptance criteria, each with a test named after it:

* the catalogue holds only free, official, keyless feeds, and a feed's
  entries parse with their published time,
* a headline naming a followed instrument is one ``news.mention`` on that
  instrument at the headline's own time; an unrelated headline is nothing,
* an agent chooses which sources it wants and says why, or wants none and
  says why; a source outside the catalogue is refused,
* the service reads only what was asked for, under a news grant, and a feed
  that is down is one incident; a news grant fetches no bars,
* a burst carries its threshold, and a mechanism can fire on it,
* the loop's source action seats a market-intelligence agent and is exhausted
  once every one of them has answered on the catalogue,
* the judge is shown the headline, and the station shows the requests.

**Nothing here touches the network.** Feeds are recorded XML.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import io
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.errors import IntegrityViolation
from aurelis.intel.live import CoinbaseCandles
from aurelis.intel.news import (
    BURST_MIN,
    CATALOGUE,
    RssFeed,
    Source,
    mentions_of,
    parse_rss,
    record_news,
)
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.service.grants import feed_for
from aurelis.service.loop import Service, cycle_once
from aurelis.sources.seat import (
    SourceRefused,
    active_sources,
    catalogue_digest,
    request_sources,
    seat_sources,
)
from aurelis.sources.tables import SourceRequest
from aurelis.station.app import station_app
from aurelis.world.store import World

_HOUR = 3600
_START = 1_780_000_000
_NOW = dt.datetime.fromtimestamp(_START + 200 * _HOUR + 600, tz=dt.UTC)


def _rss(items: list[tuple[str, dt.datetime]]) -> bytes:
    body = "".join(
        f"<item><title>{title}</title><link>https://example.test/{i}</link>"
        f"<pubDate>{email.utils.format_datetime(when)}</pubDate>"
        f"<description>&lt;p&gt;{title}&lt;/p&gt;</description></item>"
        for i, (title, when) in enumerate(items)
    )
    head = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    return f"{head}{body}</channel></rss>".encode()


class _Xml:
    def __init__(self, payload: bytes | Exception) -> None:
        self.payload = payload

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        if isinstance(self.payload, Exception):
            raise self.payload
        return io.BytesIO(self.payload)


def _headlines(now: dt.datetime) -> list[tuple[str, dt.datetime]]:
    return [
        ("Bitcoin breaks above its range as ETF inflows resume", now - dt.timedelta(hours=1)),
        ("Solana validators vote on fee change", now - dt.timedelta(hours=2)),
        ("A central bank speaks about rates", now - dt.timedelta(hours=3)),
    ]


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


def _grant(company: Runtime, source: str, *instruments: str) -> Any:
    with company.database.session() as session:
        return company.grants.grant(
            session,
            source=source,
            desk="crypto",
            instruments=instruments or ("BTC-USD", "SOL-USD", "ETH-USD"),
            granted_by="OPERATOR",
            reason=f"a test of the {source} grant, on the record",
        )


# ------------------------------------------------------------ the catalogue


def test_the_catalogue_holds_only_free_official_keyless_feeds_and_they_parse() -> None:
    assert CATALOGUE, "an empty catalogue asks the agents nothing"
    for source in CATALOGUE.values():
        assert source.cost == "free" and source.key == "none" and source.kind == "rss"
        assert source.url.startswith("https://")
    entries = parse_rss(_rss(_headlines(_NOW)))
    assert [e.title for e in entries][0].startswith("Bitcoin")
    assert entries[0].published == _NOW - dt.timedelta(hours=1)
    assert "<p>" not in entries[0].summary, "markup is stripped"
    feed = RssFeed(Source("t", "https://t.test/rss", "test"), opener=_Xml(_rss(_headlines(_NOW))))
    assert len(feed.entries()) == 3
    assert catalogue_digest() == catalogue_digest(CATALOGUE)


def test_a_headline_naming_an_instrument_is_one_mention_and_an_unrelated_one_is_nothing(
    company: Runtime, clock: FrozenClock
) -> None:
    instruments = ("BTC-USD", "SOL-USD", "ETH-USD", "PUMP-USD", "NEAR-USD")
    assert mentions_of("Bitcoin breaks out", instruments) == ["BTC-USD"]
    assert mentions_of("BTC and ETH rally", instruments) == ["BTC-USD", "ETH-USD"]
    assert mentions_of("a pump near the exchange", instruments) == [], (
        "tickers that are English words match only by alias"
    )
    assert mentions_of("pump.fun volumes surge", instruments) == ["PUMP-USD"]
    source = Source("t", "https://t.test/rss", "test")
    with company.database.session() as session:
        for _ in range(2):
            new, bursts = record_news(
                session,
                company.world,
                company.artifacts,
                source=source,
                entries=parse_rss(_rss(_headlines(_NOW))),
                instruments=instruments,
                clock=clock,
            )
        kinds = {
            (e.kind, e.entity_key, e.at.replace(tzinfo=dt.UTC))
            for e in World.events_between(
                session, since=_NOW - dt.timedelta(days=1), until=_NOW + dt.timedelta(days=1)
            )
        }
    assert new == 0 and bursts == 0, "read twice, recorded once, and two mentions are no burst"
    assert ("news.mention", "BTC-USD", _NOW - dt.timedelta(hours=1)) in kinds
    assert ("news.mention", "SOL-USD", _NOW - dt.timedelta(hours=2)) in kinds
    assert not any(k[1] == "ETH-USD" for k in kinds), "the rates story names nobody"


# ------------------------------------------------------------ the seat


def _chooser(reply: str) -> Any:
    def respond(request: Any) -> str:
        if "Which of these sources" in request.messages[-1].content:
            return reply
        return standins()(request)

    return respond


class _Direct:
    """A provider that answers straight from a responder, session-aware like
    the runtime's cached provider, for calls made outside a runtime."""

    name = "mock"

    def __init__(self, reply: str) -> None:
        self._inner = MockProvider(responder=_chooser(reply))

    def complete(self, session: Any, request: Any) -> Any:  # noqa: ARG002
        return self._inner.complete(request)


def test_an_agent_chooses_which_sources_it_wants_and_says_why_or_wants_none(
    settings: Settings, clock: FrozenClock
) -> None:
    built = Runtime.build(
        settings,
        clock=clock,
        provider=MockProvider(
            responder=_chooser(
                "SOURCES: theblock, decrypt\nBECAUSE: both cover listings and exchange "
                "flows on the instruments the company follows.\n"
            )
        ),
    )
    built.initialise()
    built.staff()
    try:
        _grant(built, "coinbase")
        rows = seat_sources(built, agent_handle="INTEL")
        assert [r.source for r in rows] == ["theblock", "decrypt"]
        assert all(r.wanted and "listings" in r.reason for r in rows)
        with built.database.session() as session:
            assert active_sources(session) == ["decrypt", "theblock"]
            kinds = [
                k
                for (k,) in session.execute(
                    sa.text("SELECT kind FROM events WHERE kind LIKE 'source.%' ORDER BY seq")
                )
            ]
            agent = built.roster.by_handle(session, "INTEL").ref
            none = request_sources(
                _Direct("SOURCES: none\nBECAUSE: nothing here bears on it.\n"),
                session,
                agent_ref=built.roster.by_handle(session, "QUANT").ref,
                instruments=("BTC-USD",),
                ledger=built.ledger,
                identity="You are QUANT.",
                clock=clock,
            )
            with pytest.raises(SourceRefused, match="not in the catalogue"):
                request_sources(
                    _Direct("SOURCES: twitter\nBECAUSE: everyone is there.\n"),
                    session,
                    agent_ref=agent,
                    instruments=("BTC-USD",),
                    identity="You are INTEL, again.",
                    clock=clock,
                )
        assert kinds == ["source.requested", "source.requested"]
        assert len(none) == 1 and not none[0].wanted and none[0].source == "none"
    finally:
        built.close()


# ------------------------------------------------------------ under the service


def test_the_service_reads_only_what_was_asked_for_under_a_news_grant(
    company: Runtime, clock: FrozenClock
) -> None:
    _grant(company, "news")
    feeds: dict[str, Any] = {
        name: RssFeed(CATALOGUE[name], opener=_Xml(_rss(_headlines(clock.now()))))
        for name in CATALOGUE
    }
    asked: list[str] = []

    def news(name: str) -> Any:
        asked.append(name)
        return feeds[name]

    # No model calls this wake, so the loop's own source action does not ask
    # before the test does: what is read is exactly what was requested.
    service = Service(company, news=news, cycles_per_wake=1, calls_per_day=0)
    first = cycle_once(company, service=service)
    assert asked == [] and "no source requested by an agent yet" in first.note
    assert first.fetched == (), "a news grant fetches no bars"

    with company.database.session() as session:
        request_sources(
            _Direct("SOURCES: coindesk\nBECAUSE: it carries the listings.\n"),
            session,
            agent_ref=company.roster.by_handle(session, "INTEL").ref,
            instruments=("BTC-USD",),
            ledger=company.ledger,
            clock=clock,
        )
    second = cycle_once(company, service=service)
    assert asked == ["coindesk"], "only the source that was asked for"
    assert "news: 1 source(s) read, 2 mention(s), 0 burst(s)" in second.note
    assert second.incidents == ()

    feeds["coindesk"] = RssFeed(CATALOGUE["coindesk"], opener=_Xml(OSError("refused")))
    third = cycle_once(company, service=service)
    assert len(third.incidents) == 1
    with company.database.session() as session:
        source_col = session.execute(
            sa.text("SELECT source FROM alerts WHERE ref = :r"), {"r": third.incidents[0]}
        ).scalar_one()
        grant = company.grants.active(session)[0]
        assert grant.is_news and grant.is_live
        with pytest.raises(IntegrityViolation, match="no feed for source 'news'"):
            feed_for(grant)
    assert source_col == "service.news"


# ------------------------------------------------------------ bursts and mechanisms


def test_a_burst_carries_its_threshold_and_a_mechanism_can_fire_on_it(
    company: Runtime, clock: FrozenClock
) -> None:
    from aurelis.mechanism.predictions import generate_predictions

    rows = [[_START + i * _HOUR, 99.0, 101.0, 100.0, 100.0 + i, 5.0] for i in range(201)]
    import json

    clock.set(dt.datetime.fromtimestamp(_START + 200 * _HOUR, tz=dt.UTC))
    now = clock.now()
    many = [
        (f"Bitcoin headline number {i}", now - dt.timedelta(minutes=10 * i))
        for i in range(BURST_MIN + 1)
    ]
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Xml(json.dumps(list(reversed(rows))).encode()), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=201,
        )
        new, bursts = record_news(
            session,
            company.world,
            company.artifacts,
            source=Source("t", "https://t.test/rss", "test"),
            entries=parse_rss(_rss(many)),
            instruments=("BTC-USD",),
            clock=clock,
        )
        burst = World.events_for(
            session, entity_kind="instrument", entity_key="BTC-USD", kinds=("news.burst",)
        )[0]
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="attention then flow",
            trigger_kind="news.burst",
            desk="crypto",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.6"),
            why="a burst of coverage brings in retail flow that has to buy at market.",
            other_side="the holders who sell into the attention.",
            decay="it fades as the coverage fades, within days.",
            origin="invented",
            found_on_instrument="ZZZ-USD",
            found_on_event="none",
            model="test",
        )
        run = generate_predictions(session, mechanism, clock=clock)
    assert new == BURST_MIN + 1 and bursts == 1
    assert burst.payload["mentions_6h"] == BURST_MIN + 1
    assert "trailing week" in burst.payload["threshold"]
    assert len(run.sealed) == 1, "the mechanism sealed against the spot close at the burst"


# ------------------------------------------------------------ the loop, the judge, the station


def test_the_loops_source_action_seats_market_intelligence_until_all_have_answered(
    company: Runtime,
) -> None:
    from aurelis.autonomy.agenda import _nothing_to_source, _sourceable

    with company.database.session() as session:
        assert "no data grant" in _nothing_to_source(session)
    _grant(company, "coinbase")
    with company.database.session() as session:
        agents = _sourceable(session)
        assert agents and all(a.department == "market_intelligence" for a in agents)
        assert _nothing_to_source(session) == ""
    for agent in agents:
        rows = seat_sources(company, agent_handle=agent.handle)
        assert rows, "the stand-in asks for two sources"
    with company.database.session() as session:
        assert _sourceable(session) == []
        assert "every market-intelligence agent has answered" in _nothing_to_source(session)
        assert active_sources(session) == ["coindesk", "theblock"]
        requests = session.execute(
            sa.select(sa.func.count()).select_from(SourceRequest)
        ).scalar_one()
    assert requests == 2 * len(agents)


def test_the_judge_is_shown_the_headline_and_the_station_shows_the_requests(
    company: Runtime, clock: FrozenClock
) -> None:
    from aurelis.judgement.seat import _recent_events

    _grant(company, "coinbase")
    with company.database.session() as session:
        record_news(
            session,
            company.world,
            company.artifacts,
            source=Source("t", "https://t.test/rss", "test"),
            entries=parse_rss(_rss(_headlines(clock.now()))),
            instruments=("BTC-USD",),
            clock=clock,
        )
        lines = _recent_events(session, "BTC-USD")
    assert any("news.mention" in line and "ETF inflows" in line for line in lines)
    seat_sources(company, agent_handle="INTEL")
    page = station_app(company).handle("/service", {}).body.decode()
    assert "SOURCES THE AGENTS ASKED FOR" in page.upper()
    assert "coindesk" in page and "listings, halts and flow" in page
