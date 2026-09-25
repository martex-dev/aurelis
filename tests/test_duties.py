"""M56 — every department works, every day, and the research never stops at a first success.

The acceptance criteria, each with a test named after it:

* judging and discovery are standing duties: with every mandate condition
  met, a judge with a market to judge is still seated,
* every department holds a daily duty, run by its own agent, recorded with
  that agent as the actor, and not run again inside the day,
* on an empty day the audit, integrity and health checks run and the lesson
  and memo make no model call,
* the audit raises an alert, as the auditor, on an agent whose replies are
  mostly refused,
* the integrity check raises a critical alert on a recording that no longer
  verifies,
* the health check raises an alert on a gap between wakes,
* the knowledge agent records a lesson and a brain note from what the day
  closed, and withholds one that cites a figure it was not shown,
* the research director writes a memo into the brain every seat reads,
* the wake runs the duties once a day and says so,
* an unstaffed workspace runs none: nobody holds them.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.alerts.tables import Alert
from aurelis.autonomy.agenda import action_named, choose
from aurelis.autonomy.duties import DUTIES, run_duties
from aurelis.brain.tables import BrainNote
from aurelis.core.canonical import sha256_of
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.intel.snapshots import MarketSnapshot, SnapshotBar, Snapshots
from aurelis.memory.tables import Lesson
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once

_NOW = dt.datetime(2026, 9, 25, 20, 0, tzinfo=dt.UTC)


class _Recorder:
    """The stand-ins, with every prompt kept, and optional replacements."""

    def __init__(self, **replies: str) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def __call__(self, request: LlmRequest) -> str:
        prompt = request.messages[-1].content
        self.prompts.append(prompt)
        if "Write the memo for the next day" in prompt and "memo" in self.replies:
            return self.replies["memo"]
        if "What should the company remember" in prompt and "lesson" in self.replies:
            return self.replies["lesson"]
        return standins()(request)


def _company(settings: Settings, responder: Any, *, staffed: bool = True) -> Runtime:
    built = Runtime.build(
        settings, clock=FrozenClock(_NOW), provider=MockProvider(responder=responder)
    )
    built.initialise()
    if staffed:
        built.staff()
    return built


@pytest.fixture
def company(settings: Settings) -> Any:
    built = _company(settings, _Recorder())
    try:
        yield built
    finally:
        built.close()


def _ref(company: Runtime, handle: str) -> str:
    with company.database.session() as session:
        return str(company.roster.by_handle(session, handle).ref)


def _event(company: Runtime, kind: EventKind, *, actor: str, subject: str, **payload: Any) -> None:
    with company.database.session() as session:
        company.ledger.append(
            session, kind=kind, actor=actor, subject=subject, payload=payload, at=_NOW
        )


def _snapshot(company: Runtime, symbol: str = "BTC-USD") -> str:
    with company.database.session() as session:
        ref = allocate_ref(session, RefKind.SNAPSHOT)
        stamps = [_NOW - dt.timedelta(hours=h) for h in range(5, 0, -1)]
        session.add(
            MarketSnapshot(
                snapshot_id=uuid7(),
                ref=ref,
                desk="crypto",
                source="fixture",
                endpoint="fixture",
                symbol=symbol,
                interval="1h",
                bars=len(stamps),
                first_at=stamps[0],
                last_at=stamps[-1],
                digest=sha256_of({"symbol": symbol}),
                is_live=False,
                fetched_at=_NOW - dt.timedelta(minutes=5),
            )
        )
        for ts in stamps:
            session.add(
                SnapshotBar(
                    snapshot_ref=ref,
                    timestamp=ts,
                    open="1",
                    high="1",
                    low="1",
                    close="1",
                    volume="1",
                )
            )
        session.flush()
        return ref


def _alerts(company: Runtime, source: str) -> list[Alert]:
    with company.database.session() as session:
        return list(session.execute(sa.select(Alert).where(Alert.source == source)).scalars())


# ------------------------------------------------------------ standing research


def test_judging_and_discovery_are_standing_so_research_never_stops_at_a_first_success(
    company: Runtime,
) -> None:
    assert action_named("judge").standing and action_named("discover").standing
    _snapshot(company)
    with company.database.session() as session:
        chosen = choose(session, frozenset(), budget_left=50)
    assert chosen.action is not None and chosen.action.key == "judge", chosen.reason
    assert "standing duty" in chosen.reason


# ------------------------------------------------------------ the duties


def test_every_department_holds_a_duty_run_by_its_own_agent_once_a_day(
    company: Runtime,
) -> None:
    first = run_duties(company, at=_NOW)
    again = run_duties(company, at=_NOW + dt.timedelta(hours=2))
    later = run_duties(company, at=_NOW + dt.timedelta(hours=25))
    with company.database.session() as session:
        actors = dict(
            session.execute(
                sa.text("SELECT subject, actor FROM events WHERE kind = :k ORDER BY seq LIMIT 5"),
                {"k": EventKind.DUTY_DONE.value},
            ).all()
        )
    expected = {
        "AUDIT": "audit",
        "GOV": "integrity",
        "INFRA": "health",
        "KNOW": "lessons",
        "CIO": "memo",
    }
    assert [d.duty for d in first] == [d.key for d in DUTIES]
    for handle, key in expected.items():
        assert actors[f"duty:{key}"] == _ref(company, handle), key
    assert again == [], "each duty waits a day"
    assert len(later) == len(DUTIES)


def test_on_an_empty_day_the_checks_run_and_the_thinking_duties_make_no_call(
    settings: Settings,
) -> None:
    recorder = _Recorder()
    company = _company(settings, recorder)
    try:
        done = {d.duty: d for d in run_duties(company, at=_NOW)}
    finally:
        company.close()
    assert "chain verified" in done["audit"].done
    assert "0 broken" in done["integrity"].done
    assert "wake(s) in the last day" in done["health"].done
    assert done["lessons"].calls == 0 and "no lesson asked for" in done["lessons"].done
    assert done["memo"].calls == 0 and "no memo written" in done["memo"].done
    assert recorder.prompts == []


def test_the_audit_raises_an_alert_on_an_agent_whose_replies_are_mostly_refused(
    company: Runtime,
) -> None:
    intel = _ref(company, "INTEL")
    for n in range(4):
        _event(company, EventKind.THESIS_REFUSED, actor=intel, subject=f"THS-{n}")
    _event(company, EventKind.THESIS_SEALED, actor=intel, subject="THS-9")
    (audit,) = run_duties(company, at=_NOW, only=("audit",))
    (alert,) = _alerts(company, "audit.agent")
    assert alert.subject == intel and alert.raised_by == _ref(company, "AUDIT")
    assert "4 of its 5 replies" in alert.message
    assert audit.findings == (f"{intel}: 4 of 5 replies refused",)


def test_the_integrity_check_raises_a_critical_alert_on_a_recording_that_no_longer_verifies(
    company: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _snapshot(company)
    monkeypatch.setattr(Snapshots, "verify", lambda self, session, r: (r != ref, "digest mismatch"))
    (integrity,) = run_duties(company, at=_NOW, only=("integrity",))
    (alert,) = _alerts(company, "integrity.seal")
    assert alert.subject == ref and alert.severity == "critical"
    assert alert.raised_by == _ref(company, "GOV")
    assert "1 broken" in integrity.done and integrity.findings == (f"{ref}: digest mismatch",)


def test_the_health_check_raises_an_alert_on_a_gap_between_wakes(company: Runtime) -> None:
    with company.database.session() as session:
        for hours in (10, 2):
            company.ledger.append(
                session,
                kind=EventKind.SERVICE_WOKE,
                actor="SERVICE",
                subject=f"WAKE-{hours}",
                payload={},
                at=_NOW - dt.timedelta(hours=hours),
            )
    (health,) = run_duties(company, at=_NOW, only=("health",))
    assert "2 wake(s)" in health.done
    (alert,) = _alerts(company, "infra.wakes")
    assert "8.0 hours" in alert.message and alert.raised_by == _ref(company, "INFRA")


def test_the_knowledge_agent_records_a_lesson_and_a_note_from_what_the_day_closed(
    settings: Settings,
) -> None:
    company = _company(settings, _Recorder())
    try:
        _event(
            company,
            EventKind.MECHANISM_SUSPENDED,
            actor=_ref(company, "RISK"),
            subject="MEC-0007",
            pnl="-295.00",
            episodes=11,
        )
        (lessons,) = run_duties(company, at=_NOW, only=("lessons",))
        with company.database.session() as session:
            lesson = session.execute(sa.select(Lesson)).scalar_one()
            note = session.execute(sa.select(BrainNote)).scalar_one()
    finally:
        company.close()
    know = lesson.author
    assert lessons.calls == 1 and lesson.source_ref == "MEC-0007"
    assert "confidence should follow the evidence" in lesson.statement
    assert note.author == know and note.source_ref == lesson.ref and "lesson" in note.topics


def test_a_lesson_citing_a_figure_it_was_not_shown_is_withheld(settings: Settings) -> None:
    company = _company(
        settings, _Recorder(lesson="LESSON: Momentum calls lost 73% of the time last week.\n")
    )
    try:
        _event(
            company,
            EventKind.MECHANISM_SUSPENDED,
            actor=_ref(company, "RISK"),
            subject="MEC-0007",
            pnl="-295.00",
            episodes=11,
        )
        (lessons,) = run_duties(company, at=_NOW, only=("lessons",))
        with company.database.session() as session:
            kept = session.execute(sa.select(sa.func.count()).select_from(Lesson)).scalar_one()
    finally:
        company.close()
    assert "withheld" in lessons.done and "73%" in lessons.done and kept == 0


def test_the_research_director_writes_a_memo_every_seat_reads(settings: Settings) -> None:
    from aurelis.brain.briefing import briefing

    recorder = _Recorder()
    company = _company(settings, recorder)
    try:
        _event(company, EventKind.THESIS_SEALED, actor=_ref(company, "INTEL"), subject="THS-1")
        done = {d.duty: d for d in run_duties(company, at=_NOW)}
        with company.database.session() as session:
            note = session.execute(
                sa.select(BrainNote).where(BrainNote.author == _ref(company, "CIO"))
            ).scalar_one()
            brain = briefing(session)
    finally:
        company.close()
    assert done["memo"].calls == 1 and "memo" in note.topics
    assert "say nothing on a quiet market" in note.text
    shown = next(p for p in recorder.prompts if "Write the memo for the next day" in p)
    assert "Todays Duties" in shown and "audit (" in shown, "the memo reads the checks first"
    assert "say nothing on a quiet market" in brain.notes


def test_the_wake_runs_the_duties_once_a_day_and_says_so(settings: Settings) -> None:
    company = _company(settings, standins())
    try:
        first = cycle_once(company, service=Service(company, calls_per_day=50, cycles_per_wake=1))
        company.clock.advance(hours=2)  # type: ignore[attr-defined]
        second = cycle_once(company, service=Service(company, calls_per_day=50, cycles_per_wake=1))
    finally:
        company.close()
    assert "duties: audit" in first.note and "memo (" in first.note
    assert "duties:" not in second.note


def test_an_unstaffed_workspace_runs_no_duty(settings: Settings) -> None:
    company = _company(settings, standins(), staffed=False)
    try:
        assert run_duties(company, at=_NOW) == []
    finally:
        company.close()
