"""M53 — a changed catalogue is asked about, whatever the mandate says.

After M50 and M51 put Telegram, Reddit, X and Discord in the catalogue, three
live wakes ran and no agent was asked about them: the source question came up
only while the mandate's ``sourced`` was unmet, and it had been met for days.

* the source question is put when an agent has not answered on the current
  catalogue, even with ``sourced`` met, and before the judges,
* once every agent has answered, it is not put again until the catalogue
  changes,
* an action that is not a standing duty still waits for its condition.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from aurelis.autonomy.agenda import choose
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.sources import seat
from aurelis.sources.seat import request_sources

_NOW = dt.datetime(2026, 9, 25, 17, 0, tzinfo=dt.UTC)


@pytest.fixture
def company(settings: Settings) -> Any:
    built = Runtime.build(
        settings, clock=FrozenClock(_NOW), provider=MockProvider(responder=standins())
    )
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.grants.grant(
            session,
            source="news",
            desk="crypto",
            instruments=("BTC-USD",),
            granted_by="test",
            reason="a test grant, so there is something to read sources for",
        )
    try:
        yield built
    finally:
        built.close()


class _Direct:
    name = "mock"

    def complete(self, session: Any, request: LlmRequest) -> Any:  # noqa: ARG002
        return MockProvider(
            responder=lambda _r: "SOURCES: coindesk\nBECAUSE: headlines name the coins first.\n"
        ).complete(request)


def _answer(company: Runtime) -> None:
    with company.database.session() as session:
        request_sources(
            _Direct(),
            session,
            agent_ref=company.roster.by_handle(session, "INTEL").ref,
            instruments=("BTC-USD",),
            ledger=company.ledger,
            at=_NOW,
        )


def test_a_changed_catalogue_is_asked_about_first_even_with_sourced_met(
    company: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    met = frozenset({"calibrated", "scheme"})
    with company.database.session() as session:
        first = choose(session, met, budget_left=50)
    assert first.action is not None and first.action.key == "source"
    assert "standing duty" in first.reason

    _answer(company)
    with company.database.session() as session:
        after = choose(session, met, budget_left=50)
    assert after.action is None or after.action.key != "source", "answered on this catalogue"

    monkeypatch.setattr(seat, "catalogue_digest", lambda catalogue=None: "a new catalogue")
    with company.database.session() as session:
        changed = choose(session, met, budget_left=50)
    assert changed.action is not None and changed.action.key == "source"


def test_an_action_that_is_not_a_standing_duty_still_waits_for_its_condition(
    company: Runtime,
) -> None:
    _answer(company)
    with company.database.session() as session:
        nothing_unmet = choose(session, frozenset(), budget_left=50)
    assert nothing_unmet.action is None
