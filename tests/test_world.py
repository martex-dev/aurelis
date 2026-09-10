"""M29 — the world model: entities, an immutable event stream, and relations.

The acceptance criteria, each with a test named after it:

* an event is typed, timestamped, hashed and immutable; the same fact learned
  twice is one event,
* a venue's catalogue becomes entities, relations and listing events, and a
  status change is an event,
* notable-price events are derived deterministically from a recording, with
  the recording as their source, and deriving twice records nothing new,
* the events for an entity and the co-occurrence of kinds inside a window are
  queryable,
* the judges are shown the recent events for the instrument they chose,
* the service syncs the catalogue and derives events every wake, and a
  catalogue outage is an incident,
* the world is legible on the station.

**Nothing here touches the network.** The catalogue is a recorded payload.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import CoinbaseCandles
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.world.derive import WINDOW, derive_price_events
from aurelis.world.sources import CoinbaseProducts, sync_catalogue
from aurelis.world.store import World
from aurelis.world.tables import Entity, Relation, WorldEvent

_HOUR = 3600
_START = 1_780_000_000


def _product(pid: str, status: str = "online", disabled: bool = False) -> dict[str, Any]:
    base, quote = pid.split("-")
    return {
        "id": pid,
        "base_currency": base,
        "quote_currency": quote,
        "display_name": f"{base}/{quote}",
        "status": status,
        "trading_disabled": disabled,
        "cancel_only": False,
        "post_only": False,
        "limit_only": False,
    }


class _Catalogue:
    def __init__(self, products: list[dict[str, Any]] | Exception) -> None:
        self.products = products

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        if isinstance(self.products, Exception):
            raise self.products
        return io.BytesIO(json.dumps(self.products).encode())


class _Bars:
    """A recording with one volume spike and one range break planted."""

    def __init__(self, count: int = 300) -> None:
        rows = []
        for i in range(count):
            close = 100.0 + (i % 7) * 0.1
            volume = 5.0
            if i == count - 10:
                volume = 50.0  # spike
            if i == count - 3:
                close = 130.0  # range break above
            rows.append([_START + i * _HOUR, close - 1, close + 1, close, close, volume])
        self._payload = json.dumps(list(reversed(rows))).encode()

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._payload)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 300 * _HOUR + 600, tz=dt.UTC))


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


# ------------------------------------------------------------ events


def test_an_event_is_typed_hashed_and_immutable_and_the_same_fact_is_one_event(
    company: Runtime, clock: FrozenClock
) -> None:
    world = company.world
    at = clock.now() - dt.timedelta(hours=2)
    with company.database.session() as session:
        first, created = world.record(
            session,
            kind="listing.seen",
            at=at,
            entity_kind="instrument",
            entity_key="ABC-USD",
            payload={"status": "online"},
            source="test",
        )
        again, created_again = world.record(
            session,
            kind="listing.seen",
            at=at,
            entity_kind="instrument",
            entity_key="ABC-USD",
            payload={"status": "online"},
            source="test",
        )
        differs, created_differs = world.record(
            session,
            kind="listing.seen",
            at=at,
            entity_kind="instrument",
            entity_key="ABC-USD",
            payload={"status": "offline"},
            source="test",
        )
    assert created and not created_again and created_differs
    assert first.digest == again.digest != differs.digest
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="immutable"),
    ):
        session.execute(
            sa.text("UPDATE world_events SET kind = 'x' WHERE digest = :d"), {"d": first.digest}
        )
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="immutable"),
    ):
        session.execute(sa.text("DELETE FROM world_events WHERE digest = :d"), {"d": first.digest})
    with company.database.session() as session:
        ledger = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = 'world.event_recorded'")
        ).scalar_one()
    assert ledger == 2


# ------------------------------------------------------------ the catalogue


def test_a_catalogue_becomes_entities_relations_and_listing_events(
    company: Runtime, clock: FrozenClock
) -> None:
    feed = CoinbaseProducts(opener=_Catalogue([_product("BTC-USD"), _product("ETH-USD")]))
    with company.database.session() as session:
        synced = sync_catalogue(session, company.world, feed, clock=clock)
        entities = {(e.kind, e.key) for e in session.execute(sa.select(Entity)).scalars()}
        relations = {
            (r.subject_key, r.kind, r.object_key)
            for r in session.execute(sa.select(Relation)).scalars()
        }
        seen = World.events_for(session, entity_kind="instrument", entity_key="BTC-USD")
    assert synced.seen == 2 and set(synced.new_listings) == {"BTC-USD", "ETH-USD"}
    assert ("venue", "coinbase") in entities
    assert ("instrument", "BTC-USD") in entities and ("asset", "BTC") in entities
    assert ("BTC-USD", "base_asset", "BTC") in relations
    assert ("BTC-USD", "quote_asset", "USD") in relations
    assert ("BTC-USD", "listed_on", "coinbase") in relations
    assert len(seen) == 1 and seen[0].kind == "listing.seen"
    assert seen[0].payload["first_sync"] is True, "the first sync says it is the first sync"


def test_a_status_change_and_a_disappearance_are_events(
    company: Runtime, clock: FrozenClock
) -> None:
    first = CoinbaseProducts(opener=_Catalogue([_product("BTC-USD"), _product("OLD-USD")]))
    with company.database.session() as session:
        sync_catalogue(session, company.world, first, clock=clock)
    clock.advance(hours=1)
    second = CoinbaseProducts(
        opener=_Catalogue(
            [_product("BTC-USD", status="offline", disabled=True), _product("NEW-USD")]
        )
    )
    with company.database.session() as session:
        synced = sync_catalogue(session, company.world, second, clock=clock)
        btc = World.events_for(session, entity_kind="instrument", entity_key="BTC-USD")
        old = World.events_for(session, entity_kind="instrument", entity_key="OLD-USD")
        new = World.events_for(session, entity_kind="instrument", entity_key="NEW-USD")
        entity = World.entity(session, "instrument", "BTC-USD")
    assert synced.status_changes == ("BTC-USD",)
    assert synced.new_listings == ("NEW-USD",)
    assert synced.disappeared == ("OLD-USD",)
    assert btc[0].kind == "listing.status_changed"
    assert btc[0].payload["before"]["status"] == "online"
    assert btc[0].payload["after"]["trading_disabled"] is True
    assert old[0].kind == "listing.gone"
    assert new[0].kind == "listing.seen" and new[0].payload["first_sync"] is False
    assert entity is not None and entity.attributes["status"] == "offline"


def test_a_relation_is_append_only(company: Runtime, clock: FrozenClock) -> None:
    with company.database.session() as session:
        company.world.relate(
            session, subject=("instrument", "X-Y"), kind="listed_on", obj=("venue", "v"), source="t"
        )
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="append-only"),
    ):
        session.execute(sa.text("DELETE FROM relations"))


# ------------------------------------------------------------ derived events


def test_notable_price_events_are_derived_from_a_recording_and_only_once(
    company: Runtime,
) -> None:
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Bars(300), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=300,
        )
        new = derive_price_events(session, company.world, snapshot)
        again = derive_price_events(session, company.world, snapshot)
        events = World.events_for(session, entity_kind="instrument", entity_key="BTC-USD")
    kinds = sorted(e.kind for e in events)
    assert new == len(events) >= 2 and again == 0
    assert "price.volume_spike" in kinds and "price.range_break" in kinds
    spike = next(e for e in events if e.kind == "price.volume_spike")
    assert Decimal(spike.payload["multiple"]) >= 3
    assert spike.source == f"derived:{snapshot.ref}"
    brk = next(e for e in events if e.kind == "price.range_break")
    assert brk.payload["side"] == "above" and brk.payload["window_bars"] == WINDOW


def test_co_occurrences_are_queryable_inside_a_window(company: Runtime) -> None:
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Bars(300), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=300,
        )
        derive_price_events(session, company.world, snapshot)
        pairs = World.co_occurrences(
            session,
            first_kind="price.volume_spike",
            second_kind="price.range_break",
            within=dt.timedelta(hours=24),
        )
        none = World.co_occurrences(
            session,
            first_kind="price.volume_spike",
            second_kind="price.range_break",
            within=dt.timedelta(hours=1),
        )
    assert len(pairs) == 1 and pairs[0].gap == dt.timedelta(hours=7)
    assert none == []


# ------------------------------------------------------------ the judges


def test_the_judges_are_shown_the_recent_events_for_their_instrument(
    company: Runtime, clock: FrozenClock
) -> None:
    from aurelis.judgement.seat import seat_agent

    seen: list[str] = []

    def spying(request: Any) -> str:
        seen.append(request.messages[-1].content)
        return standins()(request)

    company.provider._inner = MockProvider(responder=spying)  # noqa: SLF001 - test seam
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Bars(300), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=300,
        )
        derive_price_events(session, company.world, snapshot)
    sealed = seat_agent(company, agent_handle="INTEL")
    assert sealed is not None
    view_prompt = next(p for p in seen if "State your view on" in p)
    assert "Recent Events" in view_prompt
    assert "price.range_break" in view_prompt and "price.volume_spike" in view_prompt


# ------------------------------------------------------------ the service


def test_the_service_syncs_the_catalogue_and_derives_events_every_wake(
    company: Runtime, clock: FrozenClock
) -> None:
    from aurelis.service.loop import Service, cycle_once

    with company.database.session() as session:
        company.grants.grant(
            session,
            source="coinbase",
            desk="crypto",
            instruments=("BTC-USD",),
            granted_by="OPERATOR",
            reason="a test of the world layer in the service",
            bars=300,
        )
    service = Service(
        company,
        feeds=lambda _g: CoinbaseCandles(opener=_Bars(300), pause=0),
        catalogues=lambda _g: CoinbaseProducts(opener=_Catalogue([_product("BTC-USD")])),
        cycles_per_wake=2,
    )
    wake = cycle_once(company, service=service)
    assert "catalogue coinbase: 1 product(s)" in wake.note
    assert "price event(s) derived" in wake.note
    with company.database.session() as session:
        counts = World.counts(session)
    assert counts["entities"] >= 3 and counts["events"] >= 3

    down = Service(
        company,
        feeds=lambda _g: CoinbaseCandles(opener=_Bars(300), pause=0),
        catalogues=lambda _g: CoinbaseProducts(opener=_Catalogue(OSError("refused"))),
        cycles_per_wake=2,
    )
    second = cycle_once(company, service=down)
    assert len(second.incidents) == 1
    assert len(second.fetched) == 1, "the bars still came"


# ------------------------------------------------------------ the station


def test_the_world_is_legible_on_the_station(company: Runtime, clock: FrozenClock) -> None:
    from aurelis.station.app import station_app
    from aurelis.station.build import build_sealed

    with company.database.session() as session:
        sync_catalogue(
            session,
            company.world,
            CoinbaseProducts(opener=_Catalogue([_product("BTC-USD")])),
            clock=clock,
        )
    page = station_app(company).handle("/world", {}).body.decode()
    assert "The World" in page and "listing.seen" in page and "instrument:BTC-USD" in page
    html = build_sealed(company, company.settings.workspace / "station.html").path.read_text(
        encoding="utf-8"
    )
    assert "The World" in html
    assert isinstance(WorldEvent.__tablename__, str)
