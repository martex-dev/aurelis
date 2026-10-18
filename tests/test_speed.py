"""M67 — the company thinks faster, and uses what the subscription allows.

The acceptance criteria, each with a test named after it:

* the mandate's chain check links new events to the last one this process
  proved, and still catches a broken link, a forged hash and a missing event,
* a full pass still runs regularly, and a chain it finds broken is reported,
* the brain's briefing is reused for a few minutes instead of being rebuilt
  whenever any prediction is graded,
* bars read as plain rows are the same bars,
* the wake's call budget adapts: it shrinks after the allowance runs out and
  grows back while it does not, never above what the operator set.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import Actor, EventKind
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime

_NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def company(settings: Settings) -> Any:
    built = Runtime.build(
        settings, clock=FrozenClock(_NOW), provider=MockProvider(responder=standins())
    )
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _append(company: Runtime, n: int) -> None:
    with company.database.session() as session:
        for i in range(n):
            company.ledger.append(
                session,
                kind=EventKind.BRAIN_NOTED,
                actor=Actor.OPERATOR,
                subject=f"test-{i}",
                payload={"text": f"note {i}"},
                at=_NOW,
            )


def test_the_chain_check_links_new_events_to_the_last_one_proved(company: Runtime) -> None:
    from aurelis.mandate import standard

    standard._VERIFIED.clear()
    with company.database.session() as session:
        ok, first = standard._chain_intact(session)
    assert ok and "chain verified" in first and "linked" not in first
    _append(company, 5)
    with company.database.session() as session:
        ok, second = standard._chain_intact(session)
    assert ok and "the last 5 linked since this process's full pass" in second


def test_the_incremental_check_still_catches_a_broken_link(company: Runtime) -> None:
    from aurelis.platform.db.tables import Event

    with company.database.session() as session:
        tip = session.execute(sa.select(sa.func.max(Event.seq))).scalar_one()
        link = session.execute(sa.select(Event.chain_hash).where(Event.seq == tip)).scalar_one()
    _append(company, 3)
    with company.database.session() as session:
        assert company.ledger.verify_since(session, seq=tip, chain_hash=link).ok
        wrong = company.ledger.verify_since(session, seq=tip, chain_hash="0" * 64)
        assert not wrong.ok and "prev_hash" in str(wrong.reason)
        skipped = company.ledger.verify_since(session, seq=tip - 1, chain_hash=link)
        assert not skipped.ok


def test_a_full_pass_still_runs_and_a_broken_chain_is_reported(company: Runtime) -> None:
    from aurelis.mandate import standard

    standard._VERIFIED.clear()
    with company.database.session() as session:
        standard._chain_intact(session)
        key = str(session.get_bind().engine.url)
    seq, link, full_at, count = standard._VERIFIED[key]
    standard._VERIFIED[key] = (seq, "f" * 64, full_at, count)
    _append(company, 1)
    with company.database.session() as session:
        ok, why = standard._chain_intact(session)
    assert not ok and "BROKEN" in why
    assert key not in standard._VERIFIED, "the next check is a full pass again"


def test_bars_read_as_rows_are_the_same_bars(company: Runtime) -> None:
    import io
    import json

    from aurelis.intel.live import CoinbaseCandles

    rows = [[1_780_000_000 + i * 3600, 99.0, 101.0, 100.0, 100.5 + i, 5.0] for i in range(30)]

    def opener(request: object, timeout: int = 0) -> object:  # noqa: ARG001
        return io.BytesIO(json.dumps(list(reversed(rows))).encode())

    with company.database.session() as session:
        snap = company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=opener, pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=30,
        )
        ok, why = company.snapshots.verify(session, snap.ref)
        bars = company.snapshots.bars_of(session, snap.ref)
    assert ok, why
    assert len(bars) == 30 and bars[0].timestamp.tzinfo is not None
    assert str(bars[-1].close) in {"129.5", "129.50000000"}


def test_the_brief_is_reused_for_a_few_minutes(
    company: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aurelis.brain import briefing

    calls: list[int] = []
    real = briefing._fingerprinted

    def counting(session: Any) -> str:
        calls.append(1)
        return real(session)

    monkeypatch.setattr(briefing, "_fingerprinted", counting)
    monkeypatch.setattr(briefing, "BRIEF_TTL", 300.0)
    briefing._RECENT.clear()
    with company.database.session() as session:
        first = briefing.company_brief(session)
        _append(company, 2)
        second = briefing.company_brief(session)
    assert first == second and len(calls) == 1, "rebuilt once, reused after"
    monkeypatch.setattr(briefing, "BRIEF_TTL", 0.0)
    with company.database.session() as session:
        briefing.company_brief(session)
    assert len(calls) == 2, "with no reuse it is read again"


def test_the_wake_budget_shrinks_after_the_allowance_runs_out_and_grows_back(
    company: Runtime,
) -> None:
    from aurelis.alerts.service import Severity
    from aurelis.service.loop import ASLEEP_SOURCE, ASLEEP_SUBJECT, adaptive_wake_budget

    with company.database.session() as session:
        assert adaptive_wake_budget(session, 100, _NOW) == (100, "")
        ops = company.roster.by_handle(session, "OPS").ref
        company.alerts.raise_alert(
            session,
            severity=Severity.CRITICAL,
            source=ASLEEP_SOURCE,
            subject=ASLEEP_SUBJECT,
            message="The company is asleep. The subscription's usage allowance is spent.",
            recommended_action="wait for the reset",
            raised_by=ops,
            at=_NOW,
        )
        assert adaptive_wake_budget(session, 100, _NOW + dt.timedelta(hours=1))[0] == 50
        assert adaptive_wake_budget(session, 100, _NOW + dt.timedelta(hours=12))[0] == 75
        assert adaptive_wake_budget(session, 100, _NOW + dt.timedelta(hours=25)) == (100, "")
