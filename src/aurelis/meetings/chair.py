"""The Chair: runs the protocol, mostly without a model.

Convening, briefing, enforcing caps, selecting speakers, extracting stance,
dispatching tests, creating tasks, scoring forecasts and writing minutes are
all deterministic. Only the participants' turns and the synthesis draft cost
anything, which is why a company of a hundred agents can afford to meet.

The mechanisms, in the order they matter:

**Private forecasts before anyone speaks.** Phase FORECAST runs before OPENING,
and each participant records a probability without seeing another's. This is
the defence against an agreement cascade, and it is also the company's cheapest
honest quality signal.

**Sourced numerals.** Every turn goes through the same validator as every other
model output: a figure that was not in the evidence pack is rejected and the
turn is recorded as refused. Persuasion cannot beat evidence if a speaker
cannot invent evidence.

**Objections carry tests.** The Chair dispatches them on the objector's own
authority and the result comes back into the room.

**Dissent survives.** A decision records who disagreed and why, permanently.

**Productivity is counted.** A meeting that produced no decision, no action
item and no objection is logged unproductive, and that is a metric on the Chair
and on the type.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.interpret import UnsourcedFigures, interpret_as
from aurelis.agents.roster import Roster, StaffedAgent
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind, ModelTier
from aurelis.core.ids import RefKind, uuid7
from aurelis.meetings.challenge import dispatch, parse_spec
from aurelis.meetings.protocol import Protocol, protocol_for
from aurelis.meetings.tables import (
    ActionItem,
    Decision,
    Forecast,
    Meeting,
    MeetingObjection,
    MeetingParticipant,
    MeetingTurn,
)
from aurelis.meetings.types import (
    Attendance,
    MeetingStatus,
    MeetingType,
    ObjectionSeverity,
    ObjectionStatus,
    ObjectionType,
    Phase,
    Stance,
    TurnKind,
    opposing,
)
from aurelis.org.scopes import WriteScope
from aurelis.platform.db.refs import allocate_ref

if TYPE_CHECKING:
    from aurelis.agents.tools import ToolBox
    from aurelis.platform.artifacts.store import ArtifactStore
    from aurelis.platform.ledger.ledger import Ledger
    from aurelis.platform.llm.cache import CachingProvider
    from aurelis.platform.queue.queue import TaskQueue

__all__ = ["Chair", "MeetingOutcome", "ProposedAction", "ProposedObjection"]

_STANCE_MARKER = "STANCE:"


@dataclass(frozen=True, slots=True)
class ProposedObjection:
    """An objection somebody wants raised, before the Chair tests it."""

    author: str
    type: ObjectionType
    severity: ObjectionSeverity
    statement: str
    target: str = ""
    test: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProposedAction:
    """An action item, which will become a real task."""

    description: str
    owner: str
    task_kind: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    tokens: int = 5_000


@dataclass
class MeetingOutcome:
    """What a meeting produced."""

    ref: str
    type: MeetingType
    synthesis: str
    decision_ref: str | None
    turns: int
    rounds: int
    tokens: int
    usd: Decimal
    budget_exhausted: bool
    productive: bool
    state_changes: int
    objections: list[str]
    action_items: list[str]
    dissent: list[dict[str, Any]]
    minutes_digest: str | None

    def describe(self) -> str:
        parts = [f"{self.turns} turns", f"{self.rounds} exchange round(s)"]
        if self.objections:
            parts.append(f"{len(self.objections)} objection(s)")
        if self.action_items:
            parts.append(f"{len(self.action_items)} action item(s)")
        if self.dissent:
            parts.append(f"{len(self.dissent)} dissenting")
        if self.budget_exhausted:
            parts.append("budget exhausted")
        if not self.productive:
            parts.append("UNPRODUCTIVE")
        return ", ".join(parts)


class Chair:
    """Convenes and runs meetings."""

    __slots__ = (
        "_artifacts",
        "_clock",
        "_ledger",
        "_provider",
        "_queue",
        "_roster",
        "_rng",
        "_tools",
    )

    def __init__(
        self,
        *,
        roster: Roster,
        provider: CachingProvider,
        tools: ToolBox,
        artifacts: ArtifactStore,
        ledger: Ledger,
        queue: TaskQueue,
        clock: Clock | None = None,
        seed: int = 20260904,
    ) -> None:
        self._roster = roster
        self._provider = provider
        self._tools = tools
        self._artifacts = artifacts
        self._ledger = ledger
        self._queue = queue
        self._clock = clock or SystemClock()
        # Seeded: opening order is randomised to blunt an anchoring cascade,
        # but a meeting must still replay identically.
        self._rng = random.Random(seed)

    # ------------------------------------------------------------- convene

    def convene(
        self,
        session: Session,
        *,
        meeting_type: MeetingType,
        subject: str,
        chair: str,
        participants: tuple[str, ...],
        evidence: dict[str, Any] | None = None,
        subject_ref: str | None = None,
        trigger: str = "",
        desk: str | None = None,
        department: str | None = None,
        observers: tuple[str, ...] = (),
        at: dt.datetime | None = None,
    ) -> Meeting:
        """Assemble the room. Deterministic; costs nothing.

        The evidence pack is stored as an artifact, so what everyone was shown
        is citable exactly like any other artifact, and a claim made in the
        room can be checked against it years later.
        """
        moment = at or self._clock.now()
        protocol = protocol_for(meeting_type)

        speakers = tuple(participants[: protocol.max_participants])
        if not speakers:
            raise ValueError(
                f"cannot convene a {meeting_type} with no participants; an empty "
                "room is an abandoned meeting, not a quiet one"
            )

        ref = allocate_ref(session, RefKind.MEETING)
        pack = {
            "purpose": protocol.purpose,
            "agenda": list(protocol.agenda),
            "subject": subject,
            **(evidence or {}),
        }
        stored = self._artifacts.put_json(
            session, pack, kind="evidence_pack", produced_by=ref
        )

        meeting = Meeting(
            meeting_id=uuid7(),
            ref=ref,
            type=meeting_type.value,
            subject=subject[:256],
            trigger=trigger,
            subject_ref=subject_ref,
            department=department,
            desk=desk,
            chair=chair,
            agenda=list(protocol.agenda),
            evidence_pack=pack,
            evidence_digest=stored.digest,
            budget_tokens=protocol.max_tokens_total,
            budget_rounds=protocol.max_exchange_rounds,
            max_turn_tokens=protocol.max_tokens_per_turn,
            status=MeetingStatus.SCHEDULED,
            convened_at=moment,
        )
        session.add(meeting)
        session.flush()

        session.add(
            MeetingParticipant(
                meeting_ref=ref,
                agent_ref=chair,
                attendance=Attendance.CHAIR,
                charters_at_the_time=list(self._roster.coverage_of(session, chair)),
            )
        )
        for agent_ref in speakers:
            if agent_ref == chair:
                continue
            session.add(
                MeetingParticipant(
                    meeting_ref=ref,
                    agent_ref=agent_ref,
                    attendance=Attendance.REQUIRED,
                    charters_at_the_time=list(
                        self._roster.coverage_of(session, agent_ref)
                    ),
                )
            )
        for agent_ref in observers:
            session.add(
                MeetingParticipant(
                    meeting_ref=ref,
                    agent_ref=agent_ref,
                    attendance=Attendance.OBSERVING,
                    charters_at_the_time=list(
                        self._roster.coverage_of(session, agent_ref)
                    ),
                )
            )
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.MEETING_CONVENED,
            actor=chair,
            subject=ref,
            payload={
                "type": meeting_type.value,
                "subject": subject[:120],
                "participants": list(speakers),
                "observers": list(observers),
                "budget_tokens": protocol.max_tokens_total,
                "evidence": stored.digest[:12],
            },
            at=moment,
        )
        return meeting

    # ----------------------------------------------------------------- run

    def run(
        self,
        session: Session,
        meeting_ref: str,
        *,
        forecast_question: str = "",
        objections: tuple[ProposedObjection, ...] = (),
        actions: tuple[ProposedAction, ...] = (),
        at: dt.datetime | None = None,
    ) -> MeetingOutcome:
        """Run the protocol end to end."""
        moment = at or self._clock.now()
        meeting = self._meeting(session, meeting_ref)
        protocol = protocol_for(MeetingType(meeting.type))

        meeting.status = MeetingStatus.IN_SESSION
        session.flush()

        state = _Session(meeting=meeting, protocol=protocol, now=moment)
        speakers = self._speakers(session, meeting_ref)

        if Phase.BRIEF in protocol.phases:
            self._brief(session, state)
        if Phase.FORECAST in protocol.phases and forecast_question:
            self._forecasts(session, state, speakers, forecast_question)
        if Phase.OPENING in protocol.phases:
            self._opening(session, state, speakers)
        if Phase.EXCHANGE in protocol.phases:
            self._exchange(session, state, speakers)
        if Phase.CHALLENGE in protocol.phases:
            self._challenge(session, state, speakers, objections)

        synthesis = self._synthesis(session, state, speakers)

        decision_ref: str | None = None
        if Phase.DECIDE in protocol.phases and protocol.requires_decision:
            decision_ref = self._decide(session, state, speakers, synthesis)

        item_refs = self._assign(session, state, actions, decision_ref)

        return self._close(session, state, synthesis, decision_ref, item_refs)

    # -------------------------------------------------------------- phases

    def _brief(self, session: Session, state: _Session) -> None:
        """The same state of the world for everyone. No model call."""
        pack = state.meeting.evidence_pack
        lines = [f"Purpose: {pack.get('purpose', '')}", f"Subject: {state.meeting.subject}"]
        for item in pack.get("agenda", []):
            lines.append(f"  - {item}")
        for key, value in pack.items():
            if key in ("purpose", "agenda", "subject"):
                continue
            lines.append(f"{key}: {value}")

        self._record_turn(
            session,
            state,
            speaker=state.meeting.chair,
            phase=Phase.BRIEF,
            kind=TurnKind.BRIEF,
            body="\n".join(lines),
            stance=Stance.ABSTAINS,
            tokens=0,
            usd=Decimal("0"),
        )

    def _forecasts(
        self,
        session: Session,
        state: _Session,
        speakers: list[StaffedAgent],
        question: str,
    ) -> None:
        """Private probabilities, before anyone has heard anyone.

        Recorded rather than spoken: a forecast the room could see would be an
        opening statement, and the anchoring it exists to prevent would happen
        anyway.
        """
        for agent in speakers:
            if not agent.authority.may_write(WriteScope.FORECAST):
                continue
            if state.would_exceed(state.protocol.max_tokens_per_turn):
                state.exhaust()
                return

            material = {
                "question": question,
                "what_you_know": state.meeting.evidence_pack,
                # The forecaster's own remit is part of the question. Without
                # it every participant is asked something character-for-
                # character identical, the response cache serves them all the
                # same answer, and a phase whose entire purpose is independent
                # judgement returns perfectly correlated numbers.
                "you_are": ", ".join(agent.coverage),
                "instruction": (
                    "Answer with a probability between 0 and 1 on its own line, "
                    "prefixed with 'P:'. Then one sentence of reasoning."
                ),
            }
            try:
                interpretation = interpret_as(
                    self._provider,
                    session,
                    agent_ref=agent.ref,
                    system=_FORECAST_SYSTEM,
                    material=material,
                    tier=state.protocol.forecast_tier,
                    max_tokens=160,
                    task_ref=state.meeting.ref,
                )
            except UnsourcedFigures:
                # A forecast that cites a figure nobody supplied is not a
                # forecast. Skipped and left unrecorded rather than stored as
                # a number the agent could not justify.
                continue

            state.spend(interpretation)
            probability = _parse_probability(interpretation.text)
            session.add(
                Forecast(
                    forecast_id=uuid7(),
                    meeting_ref=state.meeting.ref,
                    agent_ref=agent.ref,
                    question=question,
                    probability=probability,
                    reasoning=interpretation.text[:2000],
                    recorded_at=state.now,
                )
            )
        session.flush()

    def _opening(
        self, session: Session, state: _Session, speakers: list[StaffedAgent]
    ) -> None:
        """One bounded turn each, in randomised order.

        Order is shuffled because whoever speaks first anchors the room, and a
        fixed order would make that anchoring a property of the roster.
        """
        order = list(speakers)
        self._rng.shuffle(order)
        for agent in order:
            self._speak(
                session,
                state,
                agent,
                phase=Phase.OPENING,
                kind=TurnKind.POSITION,
                system=_OPENING_SYSTEM,
                tier=state.protocol.opening_tier,
                extra={},
            )

    def _exchange(
        self, session: Session, state: _Session, speakers: list[StaffedAgent]
    ) -> None:
        """Capped rounds, speakers chosen by genuine disagreement."""
        for round_index in range(1, state.protocol.max_exchange_rounds + 1):
            if state.exhausted:
                return
            chosen = self._select_speakers(state, speakers)
            if not chosen:
                return  # converged: nobody is in disagreement
            state.round = round_index
            state.meeting.rounds_used = round_index
            for agent in chosen:
                self._speak(
                    session,
                    state,
                    agent,
                    phase=Phase.EXCHANGE,
                    kind=TurnKind.ARGUMENT,
                    system=_EXCHANGE_SYSTEM,
                    tier=state.protocol.exchange_tier,
                    extra={"discussion_so_far": state.recent_turns()},
                )

    def _challenge(
        self,
        session: Session,
        state: _Session,
        speakers: list[StaffedAgent],
        proposed: tuple[ProposedObjection, ...],
    ) -> None:
        """Formalise objections and settle them with their own tests."""
        by_ref = {agent.ref: agent for agent in speakers}
        dispatched = 0

        for objection in proposed:
            author = by_ref.get(objection.author)
            if author is None:
                continue
            if not author.authority.may_write(WriteScope.OBJECTION):
                self._ledger.append(
                    session,
                    kind=EventKind.PERMISSION_DENIED,
                    actor=objection.author,
                    subject=state.meeting.ref,
                    payload={"action": "raise objection", "reason": "no charter grants it"},
                    at=state.now,
                )
                continue

            ref = allocate_ref(session, RefKind.OBJECTION)
            spec = parse_spec(objection.test)

            if spec is None:
                status, result = ObjectionStatus.UNTESTABLE, {
                    "detail": "no discriminating test supplied; reported as an "
                    "unresolved limitation"
                }
            elif dispatched >= state.protocol.max_test_dispatches:
                status, result = ObjectionStatus.UNTESTABLE, {
                    "detail": "the meeting's test budget was spent; this becomes "
                    "a follow-up rather than stalling the room"
                }
            else:
                dispatched += 1
                outcome = dispatch(
                    session,
                    self._tools,
                    spec,
                    agent_ref=author.ref,
                    permitted=author.authority.tools,
                    meeting_ref=state.meeting.ref,
                )
                result = {"test": spec.describe(), **outcome.as_payload()}
                if not outcome.ran:
                    status = ObjectionStatus.UNTESTABLE
                else:
                    status = (
                        ObjectionStatus.UPHELD if outcome.upheld else ObjectionStatus.REJECTED
                    )

            session.add(
                MeetingObjection(
                    objection_id=uuid7(),
                    ref=ref,
                    meeting_ref=state.meeting.ref,
                    author=author.ref,
                    target=objection.target or state.meeting.subject_ref or "",
                    type=objection.type.value,
                    severity=objection.severity.value,
                    statement=objection.statement,
                    discriminating_test=dict(objection.test),
                    status=status.value,
                    test_result=result,
                    resolved_at=state.now if status is not ObjectionStatus.OPEN else None,
                    created_at=state.now,
                )
            )
            session.flush()
            state.objections.append(ref)

            self._record_turn(
                session,
                state,
                speaker=author.ref,
                phase=Phase.CHALLENGE,
                kind=TurnKind.OBJECTION,
                body=f"{objection.statement}\n\n{result.get('detail', '')}",
                stance=Stance.OPPOSES,
                tokens=0,
                usd=Decimal("0"),
                evidence_refs=[ref],
            )
            self._ledger.append(
                session,
                kind=EventKind.OBJECTION_RAISED,
                actor=author.ref,
                subject=ref,
                payload={
                    "meeting": state.meeting.ref,
                    "type": objection.type.value,
                    "severity": objection.severity.value,
                    "status": status.value,
                    "detail": str(result.get("detail", ""))[:200],
                },
                at=state.now,
            )

    def _synthesis(
        self, session: Session, state: _Session, speakers: list[StaffedAgent]
    ) -> str:
        """One draft of the outcome, by the Chair."""
        state.meeting.status = MeetingStatus.SYNTHESISING
        session.flush()

        chair = self._roster.get(session, state.meeting.chair)
        material = {
            "subject": state.meeting.subject,
            "agenda": list(state.meeting.agenda),
            "discussion": state.recent_turns(limit=12),
            "objections": state.objection_summary(session),
            "stances": state.stance_summary(),
        }
        try:
            interpretation = interpret_as(
                self._provider,
                session,
                agent_ref=chair.ref,
                system=_SYNTHESIS_SYSTEM,
                material=material,
                tier=state.protocol.synthesis_tier,
                max_tokens=500,
                task_ref=state.meeting.ref,
            )
        except UnsourcedFigures as error:
            # The Chair is held to the same rule as everyone else. A synthesis
            # that invents a figure is not a synthesis.
            text = f"[synthesis refused: {error}]"
            self._record_turn(
                session,
                state,
                speaker=chair.ref,
                phase=Phase.SYNTHESIS,
                kind=TurnKind.SYNTHESIS,
                body=text,
                stance=Stance.ABSTAINS,
                tokens=0,
                usd=Decimal("0"),
            )
            return text

        state.spend(interpretation)
        self._record_turn(
            session,
            state,
            speaker=chair.ref,
            phase=Phase.SYNTHESIS,
            kind=TurnKind.SYNTHESIS,
            body=interpretation.text,
            stance=Stance.ABSTAINS,
            tokens=interpretation.response.usage.total,
            usd=interpretation.response.usd,
        )
        return interpretation.text

    def _decide(
        self,
        session: Session,
        state: _Session,
        speakers: list[StaffedAgent],
        synthesis: str,
    ) -> str:
        """Record the decision, with dissent preserved.

        Dissent is extracted deterministically from final stances, not
        summarised by a model. A model asked to describe disagreement will
        smooth it; a table of who opposed cannot.
        """
        ref = allocate_ref(session, RefKind.DECISION)
        supporting: list[str] = []
        dissent: list[dict[str, Any]] = []

        for agent in speakers:
            stance = state.final_stance.get(agent.ref, Stance.UNCERTAIN)
            if stance is Stance.SUPPORTS:
                supporting.append(agent.ref)
            elif stance is Stance.OPPOSES:
                dissent.append(
                    {
                        "agent": agent.ref,
                        "stance": stance.value,
                        "reason": state.last_body.get(agent.ref, "")[:500],
                        "evidence_refs": state.last_evidence.get(agent.ref, []),
                    }
                )

        critical_open = [
            row.ref
            for row in session.execute(
                sa.select(MeetingObjection).where(
                    MeetingObjection.meeting_ref == state.meeting.ref,
                    MeetingObjection.severity == ObjectionSeverity.CRITICAL,
                    MeetingObjection.status.in_(
                        [ObjectionStatus.OPEN, ObjectionStatus.UPHELD]
                    ),
                )
            ).scalars()
        ]
        outcome = (
            f"BLOCKED: {len(critical_open)} critical objection(s) upheld or open"
            if critical_open
            else synthesis.strip()[:2000]
        )

        stored = self._artifacts.put_json(
            session,
            {
                "meeting": state.meeting.ref,
                "outcome": outcome,
                "supporting": supporting,
                "dissent": dissent,
                "blocking_objections": critical_open,
            },
            kind="decision",
            produced_by=state.meeting.ref,
        )
        session.add(
            Decision(
                decision_id=uuid7(),
                ref=ref,
                meeting_ref=state.meeting.ref,
                subject=state.meeting.subject[:256],
                outcome=outcome,
                rationale=synthesis.strip()[:4000],
                supporting=supporting,
                dissent=dissent,
                evidence_refs=[state.meeting.evidence_digest, *critical_open],
                decided_by=state.meeting.chair,
                decided_at=state.now,
                artifact_digest=stored.digest,
            )
        )
        session.flush()
        state.dissent = dissent

        self._ledger.append(
            session,
            kind=EventKind.DECISION_RECORDED,
            actor=state.meeting.chair,
            subject=ref,
            payload={
                "meeting": state.meeting.ref,
                "supporting": len(supporting),
                "dissenting": len(dissent),
                "blocked_by": critical_open,
            },
            at=state.now,
        )
        return ref

    def _assign(
        self,
        session: Session,
        state: _Session,
        actions: tuple[ProposedAction, ...],
        decision_ref: str | None,
    ) -> list[str]:
        """Turn action items into real tasks.

        An action item that lived only in minutes would be a promise nobody
        could be held to, so each becomes a queued task with an owner.
        """
        created: list[str] = []
        for action in actions:
            task_ref: str | None = None
            if action.task_kind:
                from aurelis.platform.budget.ledger import Spend

                task = self._queue.enqueue(
                    session,
                    kind=action.task_kind,
                    assignee=action.owner,
                    subject=state.meeting.ref,
                    payload=dict(action.payload),
                    allowance=Spend(tokens=action.tokens),
                    at=state.now,
                )
                task_ref = task.ref

            item_id = uuid7()
            session.add(
                ActionItem(
                    item_id=item_id,
                    meeting_ref=state.meeting.ref,
                    decision_ref=decision_ref,
                    description=action.description,
                    owner=action.owner,
                    task_ref=task_ref,
                    task_kind=action.task_kind or None,
                    created_at=state.now,
                )
            )
            created.append(task_ref or str(item_id)[:8])
        session.flush()
        return created

    # --------------------------------------------------------------- close

    def _close(
        self,
        session: Session,
        state: _Session,
        synthesis: str,
        decision_ref: str | None,
        action_items: list[str],
    ) -> MeetingOutcome:
        meeting = state.meeting
        changes = len(state.objections) + len(action_items) + (1 if decision_ref else 0)

        minutes = {
            "meeting": meeting.ref,
            "type": meeting.type,
            "subject": meeting.subject,
            "chair": meeting.chair,
            "agenda": list(meeting.agenda),
            "evidence": meeting.evidence_digest,
            "turns": state.turn_index,
            "rounds": meeting.rounds_used,
            "synthesis": synthesis,
            "decision": decision_ref,
            "dissent": state.dissent,
            "objections": state.objections,
            "action_items": action_items,
            "tokens": meeting.tokens_spent,
            "budget_exhausted": meeting.budget_exhausted,
        }
        stored = self._artifacts.put_json(
            session, minutes, kind="minutes", produced_by=meeting.ref
        )

        meeting.minutes_digest = stored.digest
        meeting.state_changes = changes
        meeting.productive = changes >= 1
        meeting.status = MeetingStatus.CLOSED
        meeting.closed_at = state.now
        session.flush()

        for agent_ref, stance in state.final_stance.items():
            row = session.get(MeetingParticipant, (meeting.ref, agent_ref))
            if row is not None:
                row.final_stance = stance.value
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.MEETING_CLOSED,
            actor=meeting.chair,
            subject=meeting.ref,
            payload={
                "type": meeting.type,
                "turns": state.turn_index,
                "rounds": meeting.rounds_used,
                "tokens": meeting.tokens_spent,
                "productive": meeting.productive,
                "state_changes": changes,
                "budget_exhausted": meeting.budget_exhausted,
                "minutes": stored.digest[:12],
            },
            at=state.now,
        )
        if not meeting.productive:
            self._ledger.append(
                session,
                kind=EventKind.MEETING_UNPRODUCTIVE,
                actor=meeting.chair,
                subject=meeting.ref,
                payload={
                    "type": meeting.type,
                    "reason": "no decision, action item or objection was produced",
                },
                at=state.now,
            )

        return MeetingOutcome(
            ref=meeting.ref,
            type=MeetingType(meeting.type),
            synthesis=synthesis,
            decision_ref=decision_ref,
            turns=state.turn_index,
            rounds=meeting.rounds_used,
            tokens=meeting.tokens_spent,
            usd=meeting.usd_spent,
            budget_exhausted=meeting.budget_exhausted,
            productive=meeting.productive,
            state_changes=changes,
            objections=list(state.objections),
            action_items=action_items,
            dissent=state.dissent,
            minutes_digest=stored.digest,
        )

    # ------------------------------------------------------------- speaking

    def _speak(
        self,
        session: Session,
        state: _Session,
        agent: StaffedAgent,
        *,
        phase: Phase,
        kind: TurnKind,
        system: str,
        tier: ModelTier,
        extra: dict[str, Any],
    ) -> None:
        """One participant's turn, budgeted and validated."""
        if state.would_exceed(state.protocol.max_tokens_per_turn):
            state.exhaust()
            return
        if not agent.authority.may_write(WriteScope.MEETING_TURN):
            return

        material = {
            "subject": state.meeting.subject,
            "agenda": list(state.meeting.agenda),
            "evidence": state.meeting.evidence_pack,
            "your_role": ", ".join(agent.coverage),
            "instruction": (
                "End with a line 'STANCE: SUPPORTS' or 'STANCE: OPPOSES' or "
                "'STANCE: UNCERTAIN'."
                + (
                    " Speculation is allowed here; mark it as such."
                    if state.protocol.speculation_allowed
                    else ""
                )
            ),
            **extra,
        }

        try:
            interpretation = interpret_as(
                self._provider,
                session,
                agent_ref=agent.ref,
                system=system,
                material=material,
                tier=tier,
                max_tokens=state.protocol.max_tokens_per_turn,
                task_ref=state.meeting.ref,
            )
        except UnsourcedFigures as error:
            # The turn is refused, not softened. A speaker cannot introduce
            # evidence, so persuasion cannot outrun it.
            self._ledger.append(
                session,
                kind=EventKind.TURN_REFUSED,
                actor=agent.ref,
                subject=state.meeting.ref,
                payload={"phase": phase.value, "reason": str(error)[:300]},
                at=state.now,
            )
            return

        state.spend(interpretation)
        stance = _parse_stance(interpretation.text)
        previous = state.final_stance.get(agent.ref)
        changed = previous if previous is not None and previous is not stance else None

        self._record_turn(
            session,
            state,
            speaker=agent.ref,
            phase=phase,
            kind=kind,
            body=interpretation.text,
            stance=stance,
            tokens=interpretation.response.usage.total,
            usd=interpretation.response.usd,
            changed_mind_from=changed,
        )

    def _record_turn(
        self,
        session: Session,
        state: _Session,
        *,
        speaker: str,
        phase: Phase,
        kind: TurnKind,
        body: str,
        stance: Stance,
        tokens: int,
        usd: Decimal,
        evidence_refs: list[str] | None = None,
        changed_mind_from: Stance | None = None,
    ) -> None:
        state.turn_index += 1
        session.add(
            MeetingTurn(
                turn_id=uuid7(),
                meeting_ref=state.meeting.ref,
                seq=state.turn_index,
                round=state.round,
                phase=phase.value,
                speaker=speaker,
                kind=kind.value,
                body=body,
                claims=[],
                evidence_refs=evidence_refs or [],
                stance=stance.value,
                changed_mind_from=changed_mind_from.value if changed_mind_from else None,
                tokens=tokens,
                usd=usd,
                created_at=state.now,
            )
        )
        session.flush()

        if kind is not TurnKind.BRIEF:
            state.final_stance[speaker] = stance
            state.last_body[speaker] = body
            state.last_evidence[speaker] = evidence_refs or []
        state.transcript.append((speaker, stance, body))
        if changed_mind_from is not None:
            self._ledger.append(
                session,
                kind=EventKind.MIND_CHANGED,
                actor=speaker,
                subject=state.meeting.ref,
                payload={"from": changed_mind_from.value, "to": stance.value},
                at=state.now,
            )

    def _select_speakers(
        self, state: _Session, speakers: list[StaffedAgent]
    ) -> list[StaffedAgent]:
        """Whoever is in genuine disagreement, and nobody else.

        A room where everyone agrees has converged and should stop; one where
        everyone is merely uncertain needs evidence, not another round.
        """
        committed = [
            agent
            for agent in speakers
            if state.final_stance.get(agent.ref, Stance.UNCERTAIN).is_committed
        ]
        conflicted = [
            agent
            for agent in committed
            if any(
                opposing(
                    state.final_stance[agent.ref],
                    state.final_stance[other.ref],
                )
                for other in committed
                if other.ref != agent.ref
            )
        ]
        return conflicted[: max(2, state.protocol.max_participants // 2)]

    # -------------------------------------------------------------- helpers

    def _speakers(self, session: Session, meeting_ref: str) -> list[StaffedAgent]:
        rows = session.execute(
            sa.select(MeetingParticipant.agent_ref)
            .where(
                MeetingParticipant.meeting_ref == meeting_ref,
                MeetingParticipant.attendance == Attendance.REQUIRED,
            )
            .order_by(MeetingParticipant.agent_ref)
        ).scalars().all()
        return [self._roster.get(session, ref) for ref in rows]

    @staticmethod
    def _meeting(session: Session, ref: str) -> Meeting:
        row = session.execute(sa.select(Meeting).where(Meeting.ref == ref)).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no meeting {ref!r}")
        return row


# ------------------------------------------------------------------- state


@dataclass
class _Session:
    """Mutable bookkeeping for one running meeting."""

    meeting: Meeting
    protocol: Protocol
    now: dt.datetime
    turn_index: int = 0
    round: int = 0
    exhausted: bool = False
    objections: list[str] = field(default_factory=list)
    dissent: list[dict[str, Any]] = field(default_factory=list)
    final_stance: dict[str, Stance] = field(default_factory=dict)
    last_body: dict[str, str] = field(default_factory=dict)
    last_evidence: dict[str, list[str]] = field(default_factory=dict)
    transcript: list[tuple[str, Stance, str]] = field(default_factory=list)

    def would_exceed(self, tokens: int) -> bool:
        if self.exhausted:
            return True
        return self.meeting.tokens_spent + tokens > self.protocol.max_tokens_total

    def exhaust(self) -> None:
        self.exhausted = True
        self.meeting.budget_exhausted = True

    def spend(self, interpretation: Any) -> None:
        self.meeting.tokens_spent += interpretation.response.usage.total
        self.meeting.usd_spent += interpretation.response.usd

    def recent_turns(self, limit: int = 6) -> list[str]:
        return [
            f"{speaker} [{stance.value}]: {body[:400]}"
            for speaker, stance, body in self.transcript[-limit:]
        ]

    def stance_summary(self) -> dict[str, str]:
        return {agent: stance.value for agent, stance in sorted(self.final_stance.items())}

    def objection_summary(self, session: Session) -> list[str]:
        rows = session.execute(
            sa.select(MeetingObjection).where(
                MeetingObjection.meeting_ref == self.meeting.ref
            )
        ).scalars().all()
        return [
            f"{row.ref} [{row.severity}/{row.status}] {row.statement[:200]} "
            f"-- {row.test_result.get('detail', '')}"
            for row in rows
        ]


# ------------------------------------------------------------------ parsing


def _parse_stance(text: str) -> Stance:
    """Read the declared stance, defaulting to uncertain.

    Deterministic and forgiving in one direction only: an absent or malformed
    marker is recorded as UNCERTAIN rather than guessed at, because inferring
    a position from prose is exactly the kind of judgement that should not be
    made silently.
    """
    for line in reversed(text.strip().splitlines()):
        stripped = line.strip().upper()
        if stripped.startswith(_STANCE_MARKER):
            token = stripped[len(_STANCE_MARKER) :].strip().split()[:1]
            if token:
                try:
                    return Stance(token[0].lower())
                except ValueError:
                    return Stance.UNCERTAIN
    return Stance.UNCERTAIN


def _parse_probability(text: str) -> Decimal:
    """Read ``P: 0.65``, clamped to [0, 1], defaulting to 0.5.

    An unparseable forecast becomes an explicit 50% — the least informative
    answer — rather than being dropped. A forecaster that keeps producing them
    scores badly, which is the correct consequence.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("P:"):
            candidate = stripped[2:].strip().split()[:1]
            if candidate:
                try:
                    value = Decimal(candidate[0].rstrip("%"))
                except Exception:  # noqa: BLE001
                    continue
                if value > 1:
                    value = value / Decimal(100)
                return max(Decimal(0), min(Decimal(1), value))
    return Decimal("0.5")


_FORECAST_SYSTEM = """You are recording a private forecast at Aurelis, before \
hearing anyone else.

Give a probability between 0 and 1 on its own line, prefixed 'P:'. Then one \
sentence saying what it rests on.

Use only figures present in the material you were given."""

_OPENING_SYSTEM = """You are stating your opening position in a meeting at \
Aurelis.

Two or three sentences: your position, the evidence it rests on, and what \
would change your mind.

Hard rules:
- Use ONLY figures present in the material you were given.
- Say what would change your mind. A position that nothing could change is \
not a position.
- End with a line 'STANCE: SUPPORTS', 'STANCE: OPPOSES' or 'STANCE: UNCERTAIN'."""

_EXCHANGE_SYSTEM = """You are in the exchange phase of a meeting at Aurelis.

Respond to what has been said. Two or three sentences.

Hard rules:
- Use ONLY figures present in the material you were given.
- If someone has changed your mind, say so plainly and change your stance. \
Updating on evidence is the job.
- End with a line 'STANCE: SUPPORTS', 'STANCE: OPPOSES' or 'STANCE: UNCERTAIN'."""

_SYNTHESIS_SYSTEM = """You are chairing a meeting at Aurelis. Draft the outcome.

Three or four sentences: what was agreed, what remains contested, and what \
happens next.

Hard rules:
- Use ONLY figures present in the material you were given.
- Do not smooth over disagreement. If the room was split, say so.
- If an objection was upheld, the outcome must reflect it."""
