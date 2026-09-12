"""M38 — a mechanism may fire on the conjunction it was shown.

The acceptance criteria, each with a test named after it:

* the agent is shown the effect after the conjunction beside the effect after
  the trigger, and may state a mechanism that fires on either,
* a conjunction mechanism seals one prediction per completed conjunction, at
  the second event's instant, and never twice,
* a mechanism on the trigger alone is unchanged, and every seal made before
  this milestone still verifies,
* the station and the CLI name what a mechanism fires on.

**Nothing here touches the network.**
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
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.tables import Thesis
from aurelis.mechanism.discovery import MechanismRefused, _material, _parse, propose_mechanism
from aurelis.mechanism.library import seal_of, verify_seal
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.standin import scripted_discovery
from aurelis.platform.llm.providers import MockProvider
from aurelis.runtime import Runtime
from aurelis.station.app import station_app
from aurelis.world.derive import derive_price_events
from aurelis.world.store import World
from aurelis.world.tables import WorldEvent

_HOUR = 3600
_START = 1_780_000_000


def _rising(count: int, *, breaks_every: int = 10) -> bytes:
    rows = []
    high = 100.0
    for i in range(count):
        if i % breaks_every == 0:
            high += 5.0
        rows.append([_START + i * _HOUR, high - 1, high + 1, high, high, 5.0])
    return json.dumps(list(reversed(rows))).encode()


class _Payload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._data)


def _on_conjunction(request: Any) -> str:
    reply = scripted_discovery(request)
    if "State a mechanism" in request.messages[-1].content:
        reply += "FIRES_ON: conjunction\n"
    return reply


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 299 * _HOUR + 600, tz=dt.UTC))


def _company(settings: Settings, clock: FrozenClock, responder: Any) -> Runtime:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=responder))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        snapshot = built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_rising(300)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=300,
        )
        derive_price_events(session, built.world, snapshot)
    return built


def _propose(company: Runtime) -> Any:
    with company.database.session() as session:
        return propose_mechanism(
            company.provider,
            session,
            company.mechanisms,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            trigger_kind="price.range_break",
            second_kind="price.range_break",
            desk="crypto",
            window_hours=48,
            ledger=company.ledger,
            artifacts=company.artifacts,
            identity="You are QUANT, a researcher.",
        )


def test_the_agent_is_shown_the_effect_after_the_conjunction_and_may_fire_on_it(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, _on_conjunction)
    try:
        with company.database.session() as session:
            pairs = World.co_occurrences(
                session,
                first_kind="price.range_break",
                second_kind="price.range_break",
                within=dt.timedelta(hours=48),
            )
            material = _material(
                "price.range_break", "price.range_break", pairs, 48, session=session
            )
        shown = material["in_sample_evidence"]
        assert "6h after the trigger" in shown and "6h after the conjunction" in shown
        assert "6h after any bar" in shown, "both beside the unconditional"

        mechanism = _propose(company)
        assert mechanism is not None
        assert mechanism.then_kind == "price.range_break" and mechanism.within_hours == 48
        assert mechanism.fires_on == "price.range_break ⇒ price.range_break ≤48h"
        assert verify_seal(mechanism)
        with company.database.session() as session:
            payload = session.execute(
                sa.text("SELECT payload FROM events WHERE kind = 'mechanism.stated'")
            ).scalar_one()
        stated = json.loads(payload) if isinstance(payload, str) else payload
        assert stated["fires_on"] == mechanism.fires_on
    finally:
        company.close()


def test_a_conjunction_mechanism_seals_once_per_completed_conjunction_at_the_second_event(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, _on_conjunction)
    try:
        mechanism = _propose(company)
        assert mechanism is not None and mechanism.then_kind
        with company.database.session() as session:
            run = generate_predictions(session, mechanism, clock=company.clock)
            again = generate_predictions(session, mechanism, clock=company.clock)
            predictions = list(
                session.execute(
                    sa.select(Thesis).where(Thesis.mechanism_ref == mechanism.ref)
                ).scalars()
            )
            breaks = list(
                session.execute(
                    sa.select(WorldEvent)
                    .where(WorldEvent.kind == "price.range_break")
                    .order_by(WorldEvent.at)
                ).scalars()
            )
        assert run.sealed and again.sealed == ()
        # Forward only: the seconds whose 24h horizon is still ahead of the
        # clock, and each of them once, even though every break after the
        # first completes several pairs (breaks every ten bars, window 48h).
        now = company.clock.now()
        expected = {
            b.at.replace(tzinfo=dt.UTC)
            for b in breaks[1:]
            if b.at.replace(tzinfo=dt.UTC) + dt.timedelta(hours=24) > now
        }
        assert {p.reference_at for p in predictions} == expected
        assert len(predictions) == len(expected), "one prediction per completed conjunction"
        assert all("⇒" in p.thesis for p in predictions)
    finally:
        company.close()


def test_a_trigger_mechanism_is_unchanged_and_earlier_seals_still_verify(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, scripted_discovery)
    try:
        mechanism = _propose(company)
        assert mechanism is not None
        assert mechanism.then_kind is None and mechanism.within_hours is None
        assert mechanism.fires_on == "price.range_break"
        # The seal of a trigger mechanism is the pre-M38 digest: the
        # conjunction fields do not enter it when they are unset.
        from aurelis.core.canonical import sha256_of
        from aurelis.core.clock import isoformat

        legacy = sha256_of(
            {
                "ref": mechanism.ref,
                "agent": mechanism.agent_ref,
                "title": mechanism.title,
                "trigger_kind": mechanism.trigger_kind,
                "desk": mechanism.desk,
                "horizon_hours": mechanism.horizon_hours,
                "direction": mechanism.direction,
                "confidence": str(
                    Decimal(str(mechanism.confidence)).quantize(Decimal("0.00000001"))
                ),
                "why": mechanism.why,
                "other_side": mechanism.other_side,
                "decay": mechanism.decay,
                "origin": mechanism.origin,
                "found_on_instrument": mechanism.found_on_instrument,
                "found_on_event": mechanism.found_on_event,
                "stated_at": isoformat(mechanism.stated_at),
            }
        )
        assert seal_of(mechanism) == legacy == mechanism.seal
        with pytest.raises(ValueError, match="both"), company.database.session() as session:
            company.mechanisms.state(
                session,
                agent_ref=mechanism.agent_ref,
                title="half a conjunction",
                trigger_kind="price.range_break",
                desk="crypto",
                horizon_hours=6,
                direction="up",
                confidence=Decimal("0.6"),
                why="a window without a second kind is not a conjunction at all.",
                other_side="nobody, because nothing fires.",
                decay="immediately, since it never starts.",
                origin="invented",
                found_on_instrument="BTC-USD",
                found_on_event="test",
                model="test",
                within_hours=6,
            )
        with pytest.raises(MechanismRefused, match="FIRES_ON"):
            _parse(
                "MECHANISM: x\nDIRECTION: up\nHORIZON: 6\nCONFIDENCE: 0.6\n"
                "WHY: twenty characters of reason, at least.\nOTHER_SIDE: the other side.\n"
                "DECAY: it decays slowly.\nFIRES_ON: sometimes\n"
            )
    finally:
        company.close()


def test_the_station_and_the_cli_name_what_a_mechanism_fires_on(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, _on_conjunction)
    try:
        mechanism = _propose(company)
        assert mechanism is not None
        page = station_app(company).handle("/mechanisms", {}).body.decode()
        assert "price.range_break ⇒ price.range_break ≤48h" in page
        detail = station_app(company).handle(f"/mechanism/{mechanism.ref}", {}).body.decode()
        assert "≤48h" in detail and "6h after the conjunction" in detail
    finally:
        company.close()
