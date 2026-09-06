"""Meetings: the protocol, the mechanisms, and the ceremonies.

The M3 acceptance criteria. Most tests script the provider, because the
interesting behaviour — disagreement, changing one's mind, an objection that
turns out to be right — only appears when agents actually say different
things.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.core.enums import EventKind, TaskStatus
from aurelis.core.errors import IntegrityViolation
from aurelis.meetings.ceremonies import (
    KICKOFF_QUESTION,
    close_out,
    hold_kickoff,
    hold_retrospective,
    kickoff_meeting_ref,
)
from aurelis.meetings.chair import ProposedAction, ProposedObjection, _parse_probability
from aurelis.meetings.challenge import parse_spec
from aurelis.meetings.forecasts import UNINFORMATIVE_BRIER
from aurelis.meetings.protocol import PROTOCOLS, protocol_for
from aurelis.meetings.tables import (
    ActionItem,
    Decision,
    Forecast,
    Meeting,
    MeetingObjection,
    MeetingTurn,
)
from aurelis.meetings.types import (
    MeetingStatus,
    MeetingType,
    ObjectionSeverity,
    ObjectionStatus,
    ObjectionType,
    Phase,
    Stance,
    opposing,
)
from aurelis.missions.states import MissionState
from aurelis.org.scopes import ToolScope
from aurelis.platform.db.tables import Task
from aurelis.runtime import Runtime


@pytest.fixture
def company(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


def _room(runtime: Runtime) -> tuple[str, tuple[str, ...]]:
    """The chair and three participants who may all speak in meetings."""
    with runtime.database.session() as session:
        chair = runtime.roster.by_handle(session, "OPS").ref
        speakers = tuple(
            runtime.roster.by_handle(session, handle).ref
            for handle in ("INTEL", "QUANT", "LEAD-R")
        )
    return chair, speakers


def _script(runtime: Runtime, *replies: str) -> None:
    """Queue scripted model replies, in order."""
    runtime.provider._inner.push(*replies)  # noqa: SLF001 - test seam


def _hold(
    runtime: Runtime,
    meeting_type: MeetingType = MeetingType.KICKOFF,
    **kwargs: object,
) -> object:
    chair, speakers = _room(runtime)
    with runtime.database.session() as session:
        meeting = runtime.chair.convene(
            session,
            meeting_type=meeting_type,
            subject="Whether to study the thing",
            chair=chair,
            participants=speakers,
            evidence={"measured_change": "0.0123"},
        )
        return runtime.chair.run(session, meeting.ref, **kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------------ protocol


def test_every_meeting_type_declares_its_caps() -> None:
    """An unbudgeted conversation is the thing meetings must never become."""
    for protocol in PROTOCOLS.values():
        assert protocol.max_tokens_total > 0
        assert protocol.max_tokens_per_turn > 0
        assert protocol.phases


def test_forecast_precedes_opening_in_every_protocol_that_has_it() -> None:
    """The defence against an agreement cascade only works beforehand."""
    for protocol in PROTOCOLS.values():
        if Phase.FORECAST in protocol.phases:
            assert protocol.phases.index(Phase.FORECAST) < protocol.phases.index(
                Phase.OPENING
            )


def test_only_meetings_with_something_to_measure_can_challenge() -> None:
    """The challenge phase dispatches a real tool call, so it belongs only to
    meeting types where an objection can be settled by measurement.

    Research Review had the only such question at M3. The Strategy Committee
    earned one at M8: "gate C measured correlation over 90 days; re-measure
    over 365 and it breaches the bound" is a discriminating test, and a
    promotion meeting that could not run it would be deciding on an argument
    it had no way to end.
    """
    with_challenge = {t for t, p in PROTOCOLS.items() if Phase.CHALLENGE in p.phases}
    assert with_challenge == {
        MeetingType.RESEARCH_REVIEW,
        MeetingType.STRATEGY_COMMITTEE,
    }


def test_brainstorm_requires_no_decision() -> None:
    """Demanding one would push a divergent meeting into converging early."""
    assert not protocol_for(MeetingType.BRAINSTORM).requires_decision
    assert protocol_for(MeetingType.BRAINSTORM).speculation_allowed


def test_standup_is_the_cheapest_type() -> None:
    cheapest = min(PROTOCOLS.values(), key=lambda p: p.max_tokens_total)
    assert cheapest.type is MeetingType.STANDUP


def test_an_unknown_meeting_type_is_refused() -> None:
    """``board`` used to be the example here. It is a real type as of M11, so
    the test now names something that genuinely is not one -- an assertion
    about a closed registry has to be checked against something outside it."""
    with pytest.raises(KeyError, match="closed registry"):
        protocol_for("all_hands")  # type: ignore[arg-type]


# ------------------------------------------------------------------ convene


def test_convening_stores_the_evidence_pack_as_an_artifact(company: Runtime) -> None:
    """What everyone was shown must be citable like anything else."""
    chair, speakers = _room(company)
    with company.database.session() as session:
        meeting = company.chair.convene(
            session,
            meeting_type=MeetingType.KICKOFF,
            subject="A subject",
            chair=chair,
            participants=speakers,
            evidence={"measured_change": "0.05"},
        )
    assert meeting.evidence_digest
    assert company.artifacts.exists(meeting.evidence_digest)


def test_an_empty_room_is_refused(company: Runtime) -> None:
    chair, _ = _room(company)
    with company.database.session() as session:  # noqa: SIM117
        with pytest.raises(ValueError, match="no participants"):
            company.chair.convene(
                session,
                meeting_type=MeetingType.STANDUP,
                subject="Nobody came",
                chair=chair,
                participants=(),
            )


def test_participants_record_the_charters_they_held(company: Runtime) -> None:
    """Coverage moves as the company splits its roles; a transcript that
    resolved authority at read time would misattribute an old argument."""
    from aurelis.meetings.tables import MeetingParticipant

    chair, speakers = _room(company)
    with company.database.session() as session:
        meeting = company.chair.convene(
            session,
            meeting_type=MeetingType.STANDUP,
            subject="s",
            chair=chair,
            participants=speakers,
        )
        rows = session.execute(
            sa.select(MeetingParticipant).where(
                MeetingParticipant.meeting_ref == meeting.ref
            )
        ).scalars().all()
    assert all(row.charters_at_the_time for row in rows)


# ----------------------------------------------------------------- the brief


def test_the_brief_costs_nothing_and_is_recorded(company: Runtime) -> None:
    outcome = _hold(company, MeetingType.STANDUP)
    with company.database.session() as session:
        brief = session.execute(
            sa.select(MeetingTurn).where(MeetingTurn.phase == Phase.BRIEF.value)
        ).scalars().one()
    assert brief.tokens == 0, "the brief is deterministic and free"
    assert brief.body
    assert brief.meeting_ref == outcome.ref


def test_everyone_sees_the_same_brief(company: Runtime) -> None:
    """No information asymmetry by accident."""
    _hold(company, MeetingType.STANDUP)
    with company.database.session() as session:
        briefs = session.execute(
            sa.select(MeetingTurn).where(MeetingTurn.phase == Phase.BRIEF.value)
        ).scalars().all()
    assert len(briefs) == 1, "one brief, read by everyone"


# ------------------------------------------------------------------ forecasts


def test_forecasts_are_recorded_before_anyone_speaks(company: Runtime) -> None:
    _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    with company.database.session() as session:
        forecasts = session.execute(sa.select(Forecast)).scalars().all()
        first_opening = session.execute(
            sa.select(MeetingTurn)
            .where(MeetingTurn.phase == Phase.OPENING.value)
            .order_by(MeetingTurn.seq)
            .limit(1)
        ).scalar_one()
    assert len(forecasts) == 3
    assert all(f.recorded_at <= first_opening.created_at for f in forecasts)


def test_one_forecast_per_agent_per_meeting(company: Runtime) -> None:
    _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    with company.database.session() as session:
        meeting = session.execute(sa.select(Meeting)).scalars().first()
        assert meeting is not None
        with pytest.raises(Exception, match="UNIQUE constraint failed"):
            session.execute(
                sa.text(
                    "INSERT INTO forecasts (forecast_id, meeting_ref, agent_ref, "
                    "question, probability, reasoning, recorded_at) VALUES "
                    "(:i, :m, 'AG-0004', 'q', '0.9', '', '2026-01-01 00:00:00')"
                ),
                {"i": "f" * 32, "m": meeting.ref},
            )


def test_a_probability_is_parsed_and_clamped() -> None:
    assert _parse_probability("P: 0.7\nbecause") == Decimal("0.7")
    assert _parse_probability("P: 70") == Decimal("0.7")
    # 9.9 asked for as a probability most plausibly means 9.9%.
    assert _parse_probability("P: 9.9") == Decimal("0.099")
    assert _parse_probability("P: 400") == Decimal("1")
    assert _parse_probability("P: -3") == Decimal("0")


def test_an_unparseable_forecast_becomes_an_explicit_fifty_percent() -> None:
    """Dropped forecasts teach nobody anything; a bad one scores badly."""
    assert _parse_probability("I have no idea") == Decimal("0.5")


def test_scoring_a_forecast_computes_its_brier(company: Runtime) -> None:
    outcome = _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    with company.database.session() as session:
        scored = company.forecasts.score(
            session, meeting_ref=outcome.ref, outcome=True, against="RETRO"
        )
    assert scored
    for forecast in scored:
        expected = (forecast.probability - Decimal(1)) ** 2
        assert forecast.brier == expected
        assert forecast.scored_against == "RETRO"


def test_always_saying_fifty_percent_is_reported_as_uninformative(
    company: Runtime,
) -> None:
    """0.25 is what you get by abstaining in numeric form."""
    outcome = _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    with company.database.session() as session:
        company.forecasts.score(
            session, meeting_ref=outcome.ref, outcome=True, against="RETRO"
        )
        calibration = company.forecasts.company_calibration(session)
    assert calibration
    for record in calibration:
        assert record.mean_brier == UNINFORMATIVE_BRIER
        assert not record.informative
        assert "no better than 50/50" in record.describe()


def test_a_confident_correct_forecast_beats_the_baseline(company: Runtime) -> None:
    _script(company, "P: 0.9\nConfident.", "P: 0.9\nConfident.", "P: 0.9\nConfident.")
    outcome = _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    with company.database.session() as session:
        company.forecasts.score(
            session, meeting_ref=outcome.ref, outcome=True, against="RETRO"
        )
        calibration = company.forecasts.company_calibration(session)
    assert all(record.informative for record in calibration)


def test_rescoring_is_refused(company: Runtime) -> None:
    """A bad prediction must not be quietly improved once more is known."""
    outcome = _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    with company.database.session() as session:
        company.forecasts.score(
            session, meeting_ref=outcome.ref, outcome=True, against="RETRO"
        )
        with pytest.raises(IntegrityViolation, match="already has"):
            company.forecasts.rescore_is_refused(session, outcome.ref)


# ------------------------------------------------------------------- turns


def test_a_turn_that_invents_a_figure_is_refused(company: Runtime) -> None:
    """Persuasion cannot beat evidence if a speaker cannot invent evidence.

    The M3 acceptance criterion.
    """
    _script(
        company,
        "The Sharpe ratio here is 2.31, which settles it.\nSTANCE: SUPPORTS",
    )
    outcome = _hold(company, MeetingType.STANDUP)

    with company.database.session() as session:
        bodies = [
            turn.body
            for turn in session.execute(
                sa.select(MeetingTurn).where(MeetingTurn.phase == Phase.OPENING.value)
            ).scalars()
        ]
        refusals = [
            event
            for event in company.ledger.tail(session, 200)
            if event.kind == EventKind.TURN_REFUSED.value
        ]

    assert not any("2.31" in body for body in bodies), "the figure reached the record"
    assert refusals, "the refusal must be recorded, not silent"
    assert outcome.turns >= 1


def test_a_declared_stance_is_read(company: Runtime) -> None:
    _script(
        company,
        "I think so.\nSTANCE: SUPPORTS",
        "I do not.\nSTANCE: OPPOSES",
        "Unclear.\nSTANCE: UNCERTAIN",
    )
    _hold(company, MeetingType.STANDUP)
    with company.database.session() as session:
        stances = {
            turn.stance
            for turn in session.execute(
                sa.select(MeetingTurn).where(MeetingTurn.phase == Phase.OPENING.value)
            ).scalars()
        }
    assert stances == {"supports", "opposes", "uncertain"}


def test_an_absent_stance_marker_is_uncertain_not_guessed(company: Runtime) -> None:
    """Inferring a position from prose is judgement that must not be silent."""
    _script(company, "Some thoughts with no marker at all.")
    _hold(company, MeetingType.STANDUP)
    with company.database.session() as session:
        turn = session.execute(
            sa.select(MeetingTurn)
            .where(MeetingTurn.phase == Phase.OPENING.value)
            .order_by(MeetingTurn.seq)
            .limit(1)
        ).scalar_one()
    assert turn.stance == Stance.UNCERTAIN


def test_turns_are_append_only(company: Runtime) -> None:
    _hold(company, MeetingType.STANDUP)
    with company.database.engine.begin() as conn:
        conn.execute(sa.text("UPDATE meeting_turns SET body = body"))  # mutable state
    with company.database.session() as session:
        assert session.execute(sa.select(sa.func.count()).select_from(MeetingTurn)).scalar_one()


def test_the_deterministic_officers_cannot_speak_in_meetings() -> None:
    """Software wearing a badge does not get a turn."""
    from aurelis.org import CHARTERS
    from aurelis.org.scopes import WriteScope as WS

    for charter_id in ("gov.registrar", "gov.custodian", "knowledge.archivist"):
        assert WS.MEETING_TURN not in CHARTERS[charter_id].write_scopes


def test_an_agent_without_the_scope_cannot_speak_through_raw_sql(
    company: Runtime,
) -> None:
    """The write-scope guard covers meetings too.

    Shown the way M1 showed it: move the coverage away, and the authority goes
    with it in the same transaction. A deletion would be refused now -- a
    charter may not be orphaned (ADR-0003) -- and a transfer is the honest
    shape of the event anyway.
    """
    with company.database.session() as session:
        registrar_only = company.roster.by_handle(session, "INFRA")
    with company.database.engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE agent_coverage SET agent_ref = :b WHERE agent_ref = :a"),
            {"a": registrar_only.ref, "b": "AG-0001"},
        )

    with pytest.raises(Exception, match="may not write meeting_turn"), \
            company.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO meeting_turns (turn_id, meeting_ref, seq, round, phase, "
                "speaker, addressed_to, kind, body, claims, evidence_refs, stance, "
                "tokens, usd, created_at) VALUES "
                "(:i, 'MTG-9999', 1, 0, 'opening', :s, '[]', 'position', 'smuggled', "
                "'[]', '[]', 'supports', 0, '0', '2026-01-01 00:00:00')"
            ),
            {"i": "a" * 32, "s": registrar_only.ref},
        )


# ---------------------------------------------------------------- exchange


def test_the_exchange_runs_only_on_genuine_disagreement(company: Runtime) -> None:
    """A room where everyone is merely uncertain needs evidence, not rounds."""
    outcome = _hold(company, MeetingType.KICKOFF)
    assert outcome.rounds == 0


def test_disagreement_triggers_exchange_rounds(company: Runtime) -> None:
    _script(
        company,
        # forecasts
        "P: 0.6", "P: 0.4", "P: 0.5",
        # openings
        "Yes.\nSTANCE: SUPPORTS",
        "No.\nSTANCE: OPPOSES",
        "Yes.\nSTANCE: SUPPORTS",
        # exchange
        "Still yes.\nSTANCE: SUPPORTS",
        "Still no.\nSTANCE: OPPOSES",
        "Still yes.\nSTANCE: SUPPORTS",
        "Still no.\nSTANCE: OPPOSES",
    )
    outcome = _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    assert outcome.rounds >= 1


def test_uncertainty_is_not_conflict() -> None:
    assert opposing(Stance.SUPPORTS, Stance.OPPOSES)
    assert not opposing(Stance.UNCERTAIN, Stance.OPPOSES)
    assert not opposing(Stance.SUPPORTS, Stance.SUPPORTS)


def test_changing_position_is_recorded(company: Runtime) -> None:
    """The behaviour the company most wants and prose hides."""
    _script(
        company,
        "P: 0.6", "P: 0.4", "P: 0.5",
        "Yes.\nSTANCE: SUPPORTS",
        "No.\nSTANCE: OPPOSES",
        "Yes.\nSTANCE: SUPPORTS",
        "You convinced me.\nSTANCE: OPPOSES",
        "Still no.\nSTANCE: OPPOSES",
        "Still yes.\nSTANCE: SUPPORTS",
        "Still no.\nSTANCE: OPPOSES",
    )
    _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    with company.database.session() as session:
        changed = session.execute(
            sa.select(MeetingTurn).where(MeetingTurn.changed_mind_from.is_not(None))
        ).scalars().all()
        events = [
            e for e in company.ledger.tail(session, 300)
            if e.kind == EventKind.MIND_CHANGED.value
        ]
    assert changed, "a position change must be visible in the transcript"
    assert events


# --------------------------------------------------------------- challenge


def test_an_objection_with_a_test_is_settled_by_running_it(company: Runtime) -> None:
    """The mechanism that makes debate end in evidence (ADR-0002)."""
    chair, speakers = _room(company)
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT")
        meeting = company.chair.convene(
            session,
            meeting_type=MeetingType.RESEARCH_REVIEW,
            subject="Does the change hold over a longer window?",
            chair=chair,
            participants=speakers,
            evidence={"claimed_change": "0.0123"},
        )
        outcome = company.chair.run(
            session,
            meeting.ref,
            objections=(
                ProposedObjection(
                    author=quant.ref,
                    type=ObjectionType.GENERALISATION_OVERREACH,
                    severity=ObjectionSeverity.MAJOR,
                    statement="Over 96 bars the series still has positive volume.",
                    test={
                        "tool": ToolScope.DATA_OHLCV.value,
                        "arguments": {"desk": "crypto", "limit": 96},
                        "field": "bar_count",
                        "comparison": "gte",
                        "value": "96",
                    },
                ),
            ),
        )
        row = session.execute(sa.select(MeetingObjection)).scalars().one()

    assert outcome.objections == [row.ref]
    assert row.status in (ObjectionStatus.UPHELD, ObjectionStatus.REJECTED)
    assert row.test_result["ran"] is True
    assert "measured" in row.test_result["detail"]


def test_an_objection_without_a_test_is_untestable_not_dropped(
    company: Runtime,
) -> None:
    chair, speakers = _room(company)
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT")
        meeting = company.chair.convene(
            session,
            meeting_type=MeetingType.RESEARCH_REVIEW,
            subject="s",
            chair=chair,
            participants=speakers,
        )
        company.chair.run(
            session,
            meeting.ref,
            objections=(
                ProposedObjection(
                    author=quant.ref,
                    type=ObjectionType.CONFOUND,
                    severity=ObjectionSeverity.MINOR,
                    statement="I have a feeling about this.",
                ),
            ),
        )
        row = session.execute(sa.select(MeetingObjection)).scalars().one()
    assert row.status == ObjectionStatus.UNTESTABLE
    assert "unresolved limitation" in row.test_result["detail"]


def test_analysts_cannot_raise_objections() -> None:
    """Challenging findings belongs to the Strategy Lab and Audit."""
    from aurelis.org import CHARTERS
    from aurelis.org.scopes import WriteScope as WS

    assert WS.OBJECTION not in CHARTERS["intel.technical_analyst"].write_scopes
    assert WS.OBJECTION in CHARTERS["strategy.critic"].write_scopes


def test_a_test_needing_a_capability_the_author_lacks_cannot_settle_it(
    company: Runtime,
) -> None:
    """Running it on the Chair's authority would launder the permission model."""
    chair, speakers = _room(company)
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT")
        meeting = company.chair.convene(
            session,
            meeting_type=MeetingType.RESEARCH_REVIEW,
            subject="s",
            chair=chair,
            participants=speakers,
        )
        company.chair.run(
            session,
            meeting.ref,
            objections=(
                ProposedObjection(
                    author=quant.ref,
                    type=ObjectionType.IMPLEMENTATION_BUG,
                    severity=ObjectionSeverity.MAJOR,
                    statement="Only a broker call could settle this.",
                    test={
                        "tool": ToolScope.BROKER_SUBMIT.value,
                        "arguments": {},
                        "field": "x",
                        "comparison": "gt",
                        "value": "0",
                    },
                ),
            ),
        )
        row = session.execute(sa.select(MeetingObjection)).scalars().one()
    assert row.status == ObjectionStatus.UNTESTABLE
    assert "does not hold" in row.test_result["detail"]


def test_a_critical_upheld_objection_blocks_the_decision(company: Runtime) -> None:
    chair, speakers = _room(company)
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT")
        meeting = company.chair.convene(
            session,
            meeting_type=MeetingType.RESEARCH_REVIEW,
            subject="s",
            chair=chair,
            participants=speakers,
            evidence={"claimed": "1"},
        )
        company.chair.run(
            session,
            meeting.ref,
            objections=(
                ProposedObjection(
                    author=quant.ref,
                    type=ObjectionType.DATA_QUALITY,
                    severity=ObjectionSeverity.CRITICAL,
                    statement="The source is not live.",
                    test={
                        "tool": ToolScope.DATA_OHLCV.value,
                        "arguments": {"desk": "crypto", "limit": 12},
                        "field": "bar_count",
                        "comparison": "eq",
                        "value": "12",
                    },
                ),
            ),
        )
        decision = session.execute(sa.select(Decision)).scalars().one()
    assert decision.outcome.startswith("BLOCKED")


def test_a_malformed_test_spec_is_refused_rather_than_guessed() -> None:
    assert parse_spec({"tool": "nonsense"}) is None
    assert parse_spec({"tool": "data.ohlcv", "comparison": "vibes"}) is None
    assert parse_spec({}) is None


def test_a_valid_test_spec_parses() -> None:
    spec = parse_spec(
        {
            "tool": "engine.features",
            "arguments": {"bars": []},
            "field": "change",
            "comparison": "lt",
            "value": "0.01",
        }
    )
    assert spec is not None
    assert "engine.features" in spec.describe()


# ---------------------------------------------------------------- decisions


def test_a_decision_preserves_dissent(company: Runtime) -> None:
    """Permanently. Smoothed-away disagreement must not look like consensus."""
    _script(
        company,
        "P: 0.6", "P: 0.4", "P: 0.5",
        "Yes.\nSTANCE: SUPPORTS",
        "No, and here is why.\nSTANCE: OPPOSES",
        "Yes.\nSTANCE: SUPPORTS",
        "Still yes.\nSTANCE: SUPPORTS",
        "Still no.\nSTANCE: OPPOSES",
        "Still yes.\nSTANCE: SUPPORTS",
        "Still no.\nSTANCE: OPPOSES",
        "The room is split.",
    )
    outcome = _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    with company.database.session() as session:
        decision = session.execute(sa.select(Decision)).scalars().one()
    assert decision.dissent, "a split room must record who dissented"
    assert outcome.dissent
    assert decision.dissent[0]["reason"]


def test_unanimous_agreement_records_no_dissent(company: Runtime) -> None:
    """Different from disagreement that was smoothed away."""
    _script(
        company,
        "P: 0.6", "P: 0.6", "P: 0.6",
        "Yes.\nSTANCE: SUPPORTS",
        "Yes.\nSTANCE: SUPPORTS",
        "Yes.\nSTANCE: SUPPORTS",
        "Agreed.",
    )
    _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    with company.database.session() as session:
        decision = session.execute(sa.select(Decision)).scalars().one()
    assert decision.dissent == []
    assert len(decision.supporting) == 3


# ------------------------------------------------------------- action items


def test_action_items_become_real_tasks(company: Runtime) -> None:
    """A promise nobody could be held to is not an action item."""
    chair, speakers = _room(company)
    with company.database.session() as session:
        meeting = company.chair.convene(
            session,
            meeting_type=MeetingType.KICKOFF,
            subject="s",
            chair=chair,
            participants=speakers,
        )
        outcome = company.chair.run(
            session,
            meeting.ref,
            actions=(
                ProposedAction(
                    description="Brief the desk",
                    owner=speakers[0],
                    task_kind="intel.briefing",
                    payload={"bars": 24},
                ),
            ),
        )
        item = session.execute(sa.select(ActionItem)).scalars().one()
        task = session.execute(
            sa.select(Task).where(Task.ref == item.task_ref)
        ).scalar_one()

    assert item.owner == speakers[0]
    assert task.kind == "intel.briefing"
    assert task.status == TaskStatus.QUEUED
    assert outcome.action_items == [task.ref]


# ------------------------------------------------------------ productivity


def test_a_meeting_that_produces_nothing_is_logged_unproductive(
    company: Runtime,
) -> None:
    """The M3 acceptance criterion.

    A Standup requires no decision, so one with no action items and no
    objections has changed nothing.
    """
    outcome = _hold(company, MeetingType.STANDUP)
    assert not outcome.productive
    assert outcome.state_changes == 0

    with company.database.session() as session:
        flagged = [
            e
            for e in company.ledger.tail(session, 200)
            if e.kind == EventKind.MEETING_UNPRODUCTIVE.value
        ]
    assert flagged


def test_a_meeting_that_decides_something_is_productive(company: Runtime) -> None:
    outcome = _hold(company, MeetingType.KICKOFF)
    assert outcome.productive
    assert outcome.decision_ref


# ----------------------------------------------------------------- budget


def test_a_meeting_stays_inside_its_declared_budget(company: Runtime) -> None:
    """The M3 acceptance criterion."""
    outcome = _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    protocol = protocol_for(MeetingType.KICKOFF)
    assert outcome.tokens <= protocol.max_tokens_total


def test_exhausting_the_budget_moves_to_synthesis_rather_than_failing(
    company: Runtime,
) -> None:
    """Running out of meeting is a normal outcome."""
    import dataclasses

    from aurelis.meetings.protocol import PROTOCOLS

    original = PROTOCOLS[MeetingType.KICKOFF]
    PROTOCOLS[MeetingType.KICKOFF] = dataclasses.replace(original, max_tokens_total=1)
    try:
        outcome = _hold(company, MeetingType.KICKOFF, forecast_question=KICKOFF_QUESTION)
    finally:
        PROTOCOLS[MeetingType.KICKOFF] = original

    assert outcome.budget_exhausted
    assert "budget exhausted" in outcome.describe()


def test_the_meeting_closes_and_stores_its_minutes(company: Runtime) -> None:
    outcome = _hold(company, MeetingType.KICKOFF)
    assert outcome.minutes_digest
    assert company.artifacts.exists(outcome.minutes_digest)
    with company.database.session() as session:
        meeting = session.execute(sa.select(Meeting)).scalars().first()
    assert meeting is not None
    assert meeting.status == MeetingStatus.CLOSED


# --------------------------------------------------------------- ceremonies


def test_a_kickoff_meeting_satisfies_the_mission_gate(company: Runtime) -> None:
    """The M2 gate, now satisfied by a meeting rather than an operator."""
    chair, speakers = _room(company)
    with company.database.session() as session:
        mission = company.missions.open_mission(
            session, objective="Study the thing", budget_tokens=60_000
        )
        ceremony = hold_kickoff(
            session,
            chair=company.chair,
            missions=company.missions,
            roster=company.roster,
            subject_ref=mission.ref,
            participants=speakers,
            chair_ref=chair,
        )
        company.missions.transition(session, mission.ref, MissionState.ACTIVE)
        refreshed = company.missions.mission(session, mission.ref)

    assert refreshed.state == MissionState.ACTIVE
    assert refreshed.kickoff_ref == ceremony.record_ref


def test_the_kickoff_record_says_a_meeting_produced_it(company: Runtime) -> None:
    from aurelis.missions.tables import Kickoff

    chair, speakers = _room(company)
    with company.database.session() as session:
        mission = company.missions.open_mission(session, objective="o", budget_tokens=60_000)
        hold_kickoff(
            session,
            chair=company.chair,
            missions=company.missions,
            roster=company.roster,
            subject_ref=mission.ref,
            participants=speakers,
            chair_ref=chair,
        )
        record = session.execute(sa.select(Kickoff)).scalars().one()
    assert record.kind == "meeting"
    assert record.authorised_by.startswith("MTG-")


def test_the_retrospective_scores_the_kickoffs_forecasts(company: Runtime) -> None:
    """Closing the loop: predicted, then measured against the record."""
    chair, speakers = _room(company)
    with company.database.session() as session:
        mission = company.missions.open_mission(session, objective="o", budget_tokens=60_000)
        hold_kickoff(
            session,
            chair=company.chair,
            missions=company.missions,
            roster=company.roster,
            subject_ref=mission.ref,
            participants=speakers,
            chair_ref=chair,
        )
        company.missions.transition(session, mission.ref, MissionState.ACTIVE)
        kickoff_ref = kickoff_meeting_ref(session, mission.ref)

        hold_retrospective(
            session,
            chair=company.chair,
            missions=company.missions,
            roster=company.roster,
            scorer=company.forecasts,
            subject_ref=mission.ref,
            participants=speakers,
            chair_ref=chair,
            kickoff_meeting_ref=kickoff_ref,
        )
        close_out(session, company.missions, mission.ref)

        scored = session.execute(
            sa.select(Forecast).where(Forecast.meeting_ref == kickoff_ref)
        ).scalars().all()
        refreshed = company.missions.mission(session, mission.ref)

    assert scored
    assert all(f.scored_at is not None for f in scored)
    assert refreshed.state == MissionState.CLOSED


def test_the_retrospective_sees_the_outcomes_before_anyone_speaks(
    company: Runtime,
) -> None:
    """The room discusses what happened, not what it remembers happening."""
    chair, speakers = _room(company)
    with company.database.session() as session:
        mission = company.missions.open_mission(session, objective="o", budget_tokens=60_000)
        hold_kickoff(
            session,
            chair=company.chair,
            missions=company.missions,
            roster=company.roster,
            subject_ref=mission.ref,
            participants=speakers,
            chair_ref=chair,
        )
        company.missions.transition(session, mission.ref, MissionState.ACTIVE)
        hold_retrospective(
            session,
            chair=company.chair,
            missions=company.missions,
            roster=company.roster,
            scorer=company.forecasts,
            subject_ref=mission.ref,
            participants=speakers,
            chair_ref=chair,
        )
        retro = session.execute(
            sa.select(Meeting).where(Meeting.type == MeetingType.RETROSPECTIVE.value)
        ).scalars().one()

    assert "outcomes" in retro.evidence_pack
    assert "failed" in retro.evidence_pack["outcomes"]


def test_the_whole_ceremony_leaves_a_verifiable_ledger(company: Runtime) -> None:
    chair, speakers = _room(company)
    with company.database.session() as session:
        mission = company.missions.open_mission(session, objective="o", budget_tokens=60_000)
        hold_kickoff(
            session,
            chair=company.chair,
            missions=company.missions,
            roster=company.roster,
            subject_ref=mission.ref,
            participants=speakers,
            chair_ref=chair,
        )
        assert company.ledger.verify(session).ok
