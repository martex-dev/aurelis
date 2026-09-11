"""M36 — Mission Control shows the hunt.

The acceptance criteria, each with a test named after it:

* a mechanism has a page: the statement, what the agent was shown, every
  prediction with its outcome, the tally by instrument, and the paper trades,
* the mechanisms page shows who declined a conjunction and why, and each
  mechanism links to its page,
* a mechanism's page shows the others who were shown its trigger and declined,
* an unknown mechanism is not found.

**Nothing here touches the network.** Recordings are recorded payloads and
the model is the scripted stand-in.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from typing import Any

import pytest

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.resolution import resolve_due
from aurelis.mechanism.discovery import propose_mechanism
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.standin import scripted_discovery
from aurelis.platform.llm.providers import MockProvider
from aurelis.runtime import Runtime
from aurelis.station.app import station_app
from aurelis.world.derive import derive_price_events

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


def _declining_then_stating(request: Any) -> str:
    """One agent declines with a reason; every other prompt is the stand-in."""
    prompt = request.messages[-1].content
    if "State a mechanism" in prompt and "You are CRIT" in (request.system or ""):
        return (
            "MECHANISM: nothing\n"
            "BECAUSE: sixteen occurrences on one instrument is thin, and a break "
            "that follows a break is what a trend looks like from inside.\n"
        )
    return scripted_discovery(request)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 299 * _HOUR + 600, tz=dt.UTC))


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(
        settings, clock=clock, provider=MockProvider(responder=_declining_then_stating)
    )
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
    try:
        yield built
    finally:
        built.close()


def _propose(company: Runtime, handle: str, *, identity: str = "") -> Any:
    with company.database.session() as session:
        return propose_mechanism(
            company.provider,
            session,
            company.mechanisms,
            agent_ref=company.roster.by_handle(session, handle).ref,
            trigger_kind="price.range_break",
            second_kind="price.range_break",
            desk="crypto",
            window_hours=48,
            ledger=company.ledger,
            artifacts=company.artifacts,
            identity=identity,
        )


def test_a_mechanism_has_a_page_with_its_statement_evidence_predictions_and_outcomes(
    company: Runtime,
) -> None:
    mechanism = _propose(company, "QUANT", identity="You are QUANT, a researcher.")
    assert mechanism is not None and mechanism.evidence_digest
    with company.database.session() as session:
        generate_predictions(session, mechanism, clock=company.clock)
    company.clock.advance(hours=30)
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_rising(360)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=360,
        )
        resolve_due(session, ledger=company.ledger, clock=company.clock)

    response = station_app(company).handle(f"/mechanism/{mechanism.ref}", {})
    assert response.status == 200
    page = response.body.decode()
    assert mechanism.title in page and mechanism.why[:40] in page
    assert "OTHER SIDE" in page and "DECAY" in page
    assert "WHAT THE AGENT WAS SHOWN" in page.upper()
    assert "in sample: 6h after the trigger" in page, "the evidence artifact is unfolded"
    assert "6h after any bar" in page, "beside the unconditional"
    assert "BY INSTRUMENT" in page.upper() and "BTC-USD" in page
    assert "RIGHT" in page, "a scored prediction shows its outcome"
    assert "BASE RATE" in page.upper()
    assert "/thesis/THS-" in page, "every prediction links to its thesis"
    assert "PAPER TRADES" in page.upper()


def test_the_mechanisms_page_shows_who_declined_and_why_and_links_each_mechanism(
    company: Runtime,
) -> None:
    declined = _propose(company, "CRITIC", identity="You are CRITIC, the critic.")
    assert declined is None
    stated = _propose(company, "QUANT", identity="You are QUANT, a researcher.")
    assert stated is not None

    page = station_app(company).handle("/mechanisms", {}).body.decode()
    assert "DECLINED, AND WHY" in page.upper()
    assert "sixteen occurrences on one instrument is thin" in page
    assert "price.range_break → price.range_break" in page
    assert f"href='/mechanism/{stated.ref}'" in page
    with company.database.session() as session:
        critic = company.roster.by_handle(session, "CRITIC").ref
    assert f"/agent/{critic}" in page


def test_a_mechanisms_page_shows_the_others_shown_its_trigger_who_declined(
    company: Runtime,
) -> None:
    _propose(company, "CRITIC", identity="You are CRITIC, the critic.")
    stated = _propose(company, "QUANT", identity="You are QUANT, a researcher.")
    assert stated is not None
    page = station_app(company).handle(f"/mechanism/{stated.ref}", {}).body.decode()
    assert "WHO DECLINED" in page.upper()
    assert "what a trend looks like from inside" in page


def test_an_unknown_mechanism_is_not_found(company: Runtime) -> None:
    response = station_app(company).handle("/mechanism/MEC-9999", {})
    assert response.status == 404
    assert "MEC-9999" in response.body.decode()
