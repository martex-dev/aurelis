"""Read-only projections. The station's only contact with the record.

Every function here takes a session and returns view models built from
:class:`~aurelis.station.figures.Figure`, which cannot hold a number without a
citation. Nothing in this module writes, and nothing in it decides: the station
draws verdicts the company reached, and computes none of its own. A station
that derived conclusions would be a second, unversioned source of truth
competing with the ledger.

Two habits run through the whole file.

**Rooms that have done nothing are drawn as idle, not omitted.** A department
with no agents, a desk scheduled for M12, a strategy table that does not exist
yet — each reports its true, empty state. `NO DATA` where nothing was measured,
`0` where something was measured and came back zero. Those are different
sentences and the type keeps them apart.

**Counts of things the milestone has not built yet are absent, not zero.**
Strategies, orders and risk assessments arrive in M8 and M9. Reporting `0
strategies` today would be a fabricated fact about an empty world; reporting
`NO DATA — the strategy record arrives in M8` is what is actually true.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent, AgentState, ToolCall
from aurelis.alerts.tables import Alert
from aurelis.meetings.tables import (
    Decision,
    Forecast,
    Meeting,
    MeetingObjection,
    MeetingParticipant,
    MeetingTurn,
)
from aurelis.meetings.types import MeetingStatus
from aurelis.memory.tables import CorpusReconciliation, CorpusTrial, Lesson
from aurelis.missions.states import MissionState
from aurelis.missions.tables import Mission, Project, WorkItem
from aurelis.org.departments import DEPARTMENTS, Department
from aurelis.org.desks import DESKS, Desk, DeskStatus
from aurelis.org.registry import charter, resolve_authority
from aurelis.platform.db.tables import CostEntry, Event, ModelCall, Task
from aurelis.research.states import HypothesisState
from aurelis.research.tables import (
    Evidence,
    Experiment,
    Finding,
    Hypothesis,
    Registration,
    Result,
    Run,
)
from aurelis.station.figures import Figure, Source
from aurelis.strategy.tables import Strategy

__all__ = [
    "AgentView",
    "CompanyStatus",
    "DepartmentView",
    "DeskView",
    "GraveyardView",
    "HypothesisView",
    "KnowledgeView",
    "MeetingView",
    "MissionView",
    "RoomStatus",
    "TimelineEntry",
    "agent_view",
    "company_status",
    "department_view",
    "desk_view",
    "graveyard_view",
    "hypothesis_view",
    "knowledge_view",
    "meeting_view",
    "mission_view",
    "room_statuses",
    "timeline",
]

_NOT_YET: dict[str, str] = {}
"""What the station cannot show because it does not exist yet.

Named individually rather than hidden. A room whose instruments read `NO DATA —
arrives in M8` tells a reader something true; the same room silently omitted
tells them the company has no risk function.

Empty as of M9: strategies, the book, risk and orders all have records now, and
alerts arrived with paper trading. The map stays because the *next* layer will
need it, and because an empty one is a checkable statement that nothing on the
station is a placeholder.
"""


# --------------------------------------------------------------- company


@dataclass(frozen=True, slots=True)
class CompanyStatus:
    """The header plate: what is happening, right now, in eight numbers."""

    agents: Figure
    working: Figure
    missions_open: Figure
    meetings_held: Figure
    hypotheses_settled: Figure
    events: Figure
    spend_usd: Figure
    desks_active: Figure
    chain_ok: bool
    chain_detail: str
    alerts: Figure

    def figures(self) -> list[tuple[str, Figure]]:
        return [
            ("agents", self.agents),
            ("working", self.working),
            ("missions", self.missions_open),
            ("meetings", self.meetings_held),
            ("settled", self.hypotheses_settled),
            ("events", self.events),
            ("spend", self.spend_usd),
            ("desks", self.desks_active),
            ("alerts", self.alerts),
        ]


def company_status(session: Session, *, chain_ok: bool, chain_detail: str) -> CompanyStatus:
    agents = _count(session, Agent)
    working = _count(
        session,
        Agent,
        Agent.state.in_([AgentState.WORKING.value, AgentState.IN_MEETING.value]),
        detail="state in (working, in_meeting)",
    )
    missions = _count(
        session,
        Mission,
        Mission.state.notin_(
            [
                MissionState.CLOSED.value,
                MissionState.CANCELLED.value,
                MissionState.BUDGET_EXHAUSTED.value,
            ]
        ),
        detail="state not in (closed, cancelled, budget_exhausted)",
    )
    meetings = _count(
        session, Meeting, Meeting.status == MeetingStatus.CLOSED.value, detail="closed"
    )
    settled = _count(
        session,
        Hypothesis,
        Hypothesis.settled_at.is_not(None),
        detail="settled_at is not null",
    )
    events = _count(session, Event)

    total = session.execute(sa.select(sa.func.sum(CostEntry.usd))).scalar()
    spend = Figure(
        Decimal(str(total or 0)),
        Source.table("cost_entries", "sum(usd) over every scope"),
        unit="USD",
    )

    active = sum(1 for spec in DESKS.values() if spec.status is DeskStatus.ACTIVE)
    desks = Figure(
        active,
        Source.registry("desks", f"status = active, of {len(DESKS)} registered"),
    )

    return CompanyStatus(
        agents=agents,
        working=working,
        missions_open=missions,
        meetings_held=meetings,
        hypotheses_settled=settled,
        events=events,
        spend_usd=spend,
        desks_active=desks,
        chain_ok=chain_ok,
        chain_detail=chain_detail,
        alerts=_count(
            session,
            Alert,
            Alert.resolved_at.is_(None),
            detail="unresolved",
        ),
    )


# ------------------------------------------------------------------ rooms


@dataclass(frozen=True, slots=True)
class RoomStatus:
    """What a room's status plate reads, and why.

    ``plate`` is one of the five words the station is allowed to show:
    ``WORKING``, ``IN MEETING``, ``IDLE``, ``UNSTAFFED``, ``NO DATA``. It is
    read off the agent states in that department, never guessed.
    """

    department: Department
    plate: str
    headcount: Figure
    working: Figure
    tone: str

    @property
    def busy(self) -> bool:
        return self.plate in ("WORKING", "IN MEETING")


def room_statuses(session: Session) -> dict[Department, RoomStatus]:
    """Occupancy for every department in the registry, staffed or not."""
    rows = Counter(
        (str(department), str(state))
        for department, state in session.execute(
            sa.select(Agent.department, Agent.state)
        ).all()
    )

    statuses: dict[Department, RoomStatus] = {}
    for department in DEPARTMENTS:
        counts = {
            state: count
            for (dept, state), count in rows.items()
            if dept == department.value
        }
        headcount = sum(counts.values())
        busy = counts.get(AgentState.WORKING.value, 0)
        meeting = counts.get(AgentState.IN_MEETING.value, 0)

        if headcount == 0:
            plate, tone = "UNSTAFFED", "dim"
        elif meeting:
            plate, tone = "IN MEETING", "attention"
        elif busy:
            plate, tone = "WORKING", "working"
        else:
            plate, tone = "IDLE", "dim"

        statuses[department] = RoomStatus(
            department=department,
            plate=plate,
            headcount=Figure(
                headcount,
                Source.table("agents", f"department = {department.value}"),
            ),
            working=Figure(
                busy + meeting,
                Source.table(
                    "agents",
                    f"department = {department.value}, state in (working, in_meeting)",
                ),
            ),
            tone=tone,
        )
    return statuses


# ------------------------------------------------------------- department


@dataclass(frozen=True, slots=True)
class DepartmentView:
    department: Department
    name: str
    owns: str
    head_charter: str
    status: RoomStatus
    agents: list[dict[str, Any]]
    meetings: Figure
    spend: Figure
    charters: list[dict[str, str]]


def department_view(session: Session, department: Department) -> DepartmentView:
    spec = DEPARTMENTS[department]
    status = room_statuses(session)[department]

    rows = list(
        session.execute(
            sa.select(Agent)
            .where(Agent.department == department.value)
            .order_by(Agent.ref)
        ).scalars()
    )
    agents = [
        {
            "ref": row.ref,
            "handle": row.handle,
            "state": row.state,
            "seniority": row.seniority,
            "desk": row.desk or "—",
            "tier": row.tier,
        }
        for row in rows
    ]

    meetings = _count(
        session,
        Meeting,
        Meeting.department == department.value,
        detail=f"department = {department.value}",
    )
    spent = session.execute(
        sa.select(sa.func.sum(CostEntry.usd)).where(
            CostEntry.department_id == department.value
        )
    ).scalar()
    spend = Figure(
        Decimal(str(spent or 0)),
        Source.table("cost_entries", f"department_id = {department.value}"),
        unit="USD",
    )

    charters = [
        {"id": held, "title": charter(held).name}
        for held in sorted(
            {
                coverage
                for row in rows
                for coverage in _coverage(session, row.ref)
            }
        )
    ]
    return DepartmentView(
        department=department,
        name=spec.name,
        owns=spec.owns,
        head_charter=spec.head_charter,
        status=status,
        agents=agents,
        meetings=meetings,
        spend=spend,
        charters=charters,
    )


# ------------------------------------------------------------------ agent


@dataclass(frozen=True, slots=True)
class AgentView:
    ref: str
    handle: str
    department: str
    desk: str
    seniority: str
    tier: str
    state: str
    charters: list[dict[str, str]]
    can_see: list[str]
    can_write: list[str]
    tools: list[str]
    observations: Figure
    tool_calls: Figure
    refusals: Figure
    findings: Figure
    objections: Figure
    brier: Figure
    scored: Figure
    spend: Figure
    model_calls: Figure
    cache_rate: Figure
    hired_at: dt.datetime
    note: str


def agent_view(session: Session, ref: str) -> AgentView | None:
    row = session.execute(sa.select(Agent).where(Agent.ref == ref)).scalar_one_or_none()
    if row is None:
        return None

    coverage = _coverage(session, ref)
    authority = resolve_authority(coverage)

    calls = _count(session, ToolCall, ToolCall.agent_ref == ref, detail=f"agent = {ref}")
    refused = _count(
        session,
        ToolCall,
        sa.and_(ToolCall.agent_ref == ref, ToolCall.outcome == "refused"),
        detail=f"agent = {ref}, outcome = refused",
    )
    findings = _count(
        session, Finding, Finding.author == ref, detail=f"author = {ref}"
    )
    objections = _count(
        session,
        MeetingObjection,
        MeetingObjection.author == ref,
        detail=f"author = {ref}",
    )

    scored_rows = list(
        session.execute(
            sa.select(Forecast.brier).where(
                Forecast.agent_ref == ref, Forecast.brier.is_not(None)
            )
        ).scalars()
    )
    if scored_rows:
        scores = [Decimal(str(score)) for score in scored_rows if score is not None]
        mean = sum(scores, Decimal(0)) / len(scores)
        brier = Figure.derived(
            mean.quantize(Decimal("0.0001")),
            how="mean of scored Brier scores",
            sources=[Source.table("forecasts", f"agent = {ref}, brier is not null")],
        )
    else:
        brier = Figure.absent("no forecast this agent made has been scored yet")

    spent = session.execute(
        sa.select(sa.func.sum(CostEntry.usd)).where(CostEntry.actor == ref)
    ).scalar()
    model_rows = list(
        session.execute(
            sa.select(ModelCall.cache_hit).where(ModelCall.actor == ref)
        ).scalars()
    )
    hits = sum(1 for hit in model_rows if hit)
    cache_rate = (
        Figure.derived(
            Decimal(hits * 100 // len(model_rows)),
            how="cache hits as a percentage of model calls",
            sources=[Source.table("model_calls", f"actor = {ref}")],
            unit="%",
        )
        if model_rows
        else Figure.absent("this agent has made no model calls")
    )

    return AgentView(
        ref=row.ref,
        handle=row.handle,
        department=row.department,
        desk=row.desk or "—",
        seniority=row.seniority,
        tier=row.tier,
        state=row.state,
        charters=[{"id": held, "title": charter(held).name} for held in coverage],
        can_see=sorted(view.value for view in authority.read_views),
        can_write=sorted(scope.value for scope in authority.write_scopes),
        tools=sorted(tool.value for tool in authority.tools),
        observations=Figure.absent(
            "observations are attributed by desk, not by agent, at this milestone"
        ),
        tool_calls=calls,
        refusals=refused,
        findings=findings,
        objections=objections,
        brier=brier,
        scored=Figure(
            len(scored_rows),
            Source.table("forecasts", f"agent = {ref}, brier is not null"),
        ),
        spend=Figure(
            Decimal(str(spent or 0)),
            Source.table("cost_entries", f"actor = {ref}"),
            unit="USD",
        ),
        model_calls=Figure(
            len(model_rows), Source.table("model_calls", f"actor = {ref}")
        ),
        cache_rate=cache_rate,
        hired_at=row.hired_at,
        note=row.note,
    )


# ---------------------------------------------------------------- mission


@dataclass(frozen=True, slots=True)
class MissionView:
    ref: str
    objective: str
    state: str
    desk: str
    projects: list[dict[str, Any]]
    tasks_total: Figure
    tasks_done: Figure
    spend: Figure
    meetings: list[dict[str, str]]


def mission_view(session: Session, ref: str) -> MissionView | None:
    row = session.execute(
        sa.select(Mission).where(Mission.ref == ref)
    ).scalar_one_or_none()
    if row is None:
        return None

    projects = list(
        session.execute(
            sa.select(Project).where(Project.mission_ref == ref).order_by(Project.ref)
        ).scalars()
    )
    project_refs = [project.ref for project in projects]

    # Tasks reach a mission through work_items, not directly. The queue is
    # deliberately ignorant of missions, so the join goes through the table
    # that records what a task was for.
    placed = sa.select(WorkItem.task_ref).where(WorkItem.mission_ref == ref)
    total = _count(session, Task, Task.ref.in_(placed), detail=f"placed in {ref}")
    done = _count(
        session,
        Task,
        sa.and_(Task.ref.in_(placed), Task.status == "succeeded"),
        detail=f"placed in {ref}, status = succeeded",
    )
    spent = session.execute(
        sa.select(sa.func.sum(CostEntry.usd)).where(CostEntry.mission_id == ref)
    ).scalar()

    meetings = [
        {"ref": meeting.ref, "type": meeting.type, "subject": meeting.subject}
        for meeting in session.execute(
            sa.select(Meeting)
            .where(Meeting.subject_ref.in_([ref, *project_refs]))
            .order_by(Meeting.convened_at)
        ).scalars()
    ]

    return MissionView(
        ref=row.ref,
        objective=row.objective,
        state=row.state,
        desk=", ".join(str(desk) for desk in row.desks) or "—",
        projects=[
            {"ref": p.ref, "intent": p.intent, "state": p.state} for p in projects
        ],
        tasks_total=total,
        tasks_done=done,
        spend=Figure(
            Decimal(str(spent or 0)),
            Source.table("cost_entries", f"mission_id = {ref}"),
            unit="USD",
        ),
        meetings=meetings,
    )


# ---------------------------------------------------------------- meeting


@dataclass(frozen=True, slots=True)
class MeetingView:
    ref: str
    type: str
    subject: str
    status: str
    chair: str
    productive: bool
    rounds: Figure
    tokens: Figure
    usd: Figure
    participants: list[dict[str, str]]
    turns: list[dict[str, Any]]
    objections: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    forecasts: list[dict[str, Any]]
    evidence_digest: str | None


def meeting_view(session: Session, ref: str) -> MeetingView | None:
    row = session.execute(
        sa.select(Meeting).where(Meeting.ref == ref)
    ).scalar_one_or_none()
    if row is None:
        return None

    turns = [
        {
            "seq": turn.seq,
            "round": turn.round,
            "phase": turn.phase,
            "speaker": turn.speaker,
            "kind": turn.kind,
            "stance": turn.stance,
            "changed_mind_from": turn.changed_mind_from,
            "body": turn.body,
            "evidence_refs": list(turn.evidence_refs),
        }
        for turn in session.execute(
            sa.select(MeetingTurn)
            .where(MeetingTurn.meeting_ref == ref)
            .order_by(MeetingTurn.seq)
        ).scalars()
    ]
    participants = [
        {
            "agent_ref": row_.agent_ref,
            "attendance": row_.attendance,
            "final_stance": row_.final_stance or "—",
        }
        for row_ in session.execute(
            sa.select(MeetingParticipant)
            .where(MeetingParticipant.meeting_ref == ref)
            .order_by(MeetingParticipant.agent_ref)
        ).scalars()
    ]
    objections = [
        {
            "ref": obj.ref,
            "author": obj.author,
            "type": obj.type,
            "severity": obj.severity,
            "status": obj.status,
            "statement": obj.statement,
            "test": obj.discriminating_test,
            "result": obj.test_result,
        }
        for obj in session.execute(
            sa.select(MeetingObjection)
            .where(MeetingObjection.meeting_ref == ref)
            .order_by(MeetingObjection.ref)
        ).scalars()
    ]
    decisions = [
        {
            "ref": decision.ref,
            "subject": decision.subject,
            "outcome": decision.outcome,
            "rationale": decision.rationale,
            "supporting": list(decision.supporting),
            "dissent": list(decision.dissent),
            "decided_by": decision.decided_by,
        }
        for decision in session.execute(
            sa.select(Decision).where(Decision.meeting_ref == ref)
        ).scalars()
    ]
    forecasts = [
        {
            "agent_ref": forecast.agent_ref,
            "probability": forecast.probability,
            "outcome": forecast.outcome,
            "brier": forecast.brier,
            "question": forecast.question,
        }
        for forecast in session.execute(
            sa.select(Forecast)
            .where(Forecast.meeting_ref == ref)
            .order_by(Forecast.agent_ref)
        ).scalars()
    ]

    return MeetingView(
        ref=row.ref,
        type=row.type,
        subject=row.subject,
        status=row.status,
        chair=row.chair,
        productive=row.productive,
        rounds=Figure(row.rounds_used, Source.table("meetings", f"ref = {ref}")),
        tokens=Figure(row.tokens_spent, Source.table("meetings", f"ref = {ref}")),
        usd=Figure(row.usd_spent, Source.table("meetings", f"ref = {ref}"), unit="USD"),
        participants=participants,
        turns=turns,
        objections=objections,
        decisions=decisions,
        forecasts=forecasts,
        evidence_digest=row.evidence_digest,
    )


# ------------------------------------------------------------- hypothesis


@dataclass(frozen=True, slots=True)
class HypothesisView:
    ref: str
    claim: str
    state: str
    family: str
    desk: str
    author: str
    minimum_effect: Figure
    primary_metric: str
    verdict_reason: str
    registration: dict[str, Any] | None
    experiments: list[dict[str, str]]
    runs: list[dict[str, Any]]
    results: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    objections: list[dict[str, Any]]
    prior_art: list[str]


def hypothesis_view(session: Session, ref: str) -> HypothesisView | None:
    row = session.execute(
        sa.select(Hypothesis).where(Hypothesis.ref == ref)
    ).scalar_one_or_none()
    if row is None:
        return None

    registration = session.execute(
        sa.select(Registration)
        .where(Registration.hypothesis_ref == ref)
        .order_by(Registration.created_at.desc())
    ).scalars().first()

    experiments = list(
        session.execute(
            sa.select(Experiment).where(Experiment.hypothesis_ref == ref)
        ).scalars()
    )
    runs = list(
        session.execute(
            sa.select(Run)
            .where(
                Run.experiment_ref.in_([e.ref for e in experiments])
                if experiments
                else sa.false()
            )
            .order_by(Run.started_at)
        ).scalars()
    )
    results = list(
        session.execute(
            sa.select(Result)
            .where(Result.run_ref.in_([r.ref for r in runs]) if runs else sa.false())
            .order_by(Result.metric)
        ).scalars()
    )
    findings = list(
        session.execute(
            sa.select(Finding).where(Finding.hypothesis_ref == ref).order_by(Finding.ref)
        ).scalars()
    )

    return HypothesisView(
        ref=row.ref,
        claim=row.claim,
        state=row.state,
        family=row.family,
        desk=row.desk or "—",
        author=row.author,
        minimum_effect=Figure(
            row.minimum_effect, Source.table("hypotheses", f"ref = {ref}, declared before the run")
        ),
        primary_metric=row.primary_metric,
        verdict_reason=row.verdict_reason,
        registration=(
            {
                "ref": registration.ref,
                "kind": registration.kind,
                "digest": registration.spec_digest,
                "locked_at": registration.locked_at,
                "locked_by": registration.locked_by,
                "declared_cells": registration.declared_cells,
                "pass_criteria": list(registration.pass_criteria),
                "analysis_plan": registration.analysis_plan,
                "seed": registration.seed,
            }
            if registration is not None
            else None
        ),
        experiments=[
            {"ref": e.ref, "engine": e.engine, "digest": e.spec_digest} for e in experiments
        ],
        runs=[
            {
                "ref": run.ref,
                "status": run.status,
                "engine": run.engine,
                "code_version": run.code_version,
                "data_fingerprint": run.data_fingerprint,
                "seed": run.seed,
                "artifact_digest": run.artifact_digest,
            }
            for run in runs
        ],
        results=[
            {
                "metric": result.metric,
                "value": Figure(
                    result.value,
                    Source.artifact(
                        result.artifact_digest, f"{result.metric} on {result.split}"
                    ),
                ),
                "low": result.low,
                "high": result.high,
                "split": result.split,
                "computed_by": result.computed_by,
                "method": result.method,
                "artifact_digest": result.artifact_digest,
            }
            for result in results
        ],
        findings=[
            {
                "ref": finding.ref,
                "statement": finding.statement,
                "verdict": finding.verdict,
                "verdict_reason": finding.verdict_reason,
                "verdict_checks": list(finding.verdict_checks),
                "author": finding.author,
                "cap_reason": finding.confidence_cap_reason,
            }
            for finding in findings
        ],
        evidence=[
            {
                "kind": item.kind,
                "polarity": item.polarity,
                "statement": item.statement,
                "artifact_digest": item.artifact_digest,
                "author": item.author,
            }
            for item in session.execute(
                sa.select(Evidence).where(
                    Evidence.finding_ref.in_([f.ref for f in findings])
                    if findings
                    else sa.false()
                )
            ).scalars()
        ],
        objections=[
            {
                "ref": obj.ref,
                "type": obj.type,
                "severity": obj.severity,
                "status": obj.status,
                "statement": obj.statement,
                "meeting_ref": obj.meeting_ref,
                "result": obj.test_result,
            }
            for obj in session.execute(
                sa.select(MeetingObjection).where(MeetingObjection.target == ref)
            ).scalars()
        ],
        prior_art=[str(item) for item in row.prior_art],
    )


# --------------------------------------------------------------- the rest


@dataclass(frozen=True, slots=True)
class DeskView:
    desk: Desk
    name: str
    status: DeskStatus
    instruments: tuple[str, ...]
    engines: tuple[str, ...]
    calendar: str
    opens_at: str
    agents: Figure
    hypotheses: Figure
    strategies: Figure
    notes: str


def desk_view(session: Session, desk: Desk) -> DeskView:
    spec = DESKS[desk]
    return DeskView(
        desk=desk,
        name=spec.name,
        status=spec.status,
        instruments=spec.instruments,
        engines=spec.engines,
        calendar=spec.calendar,
        opens_at=spec.opens_at_milestone,
        agents=_count(session, Agent, Agent.desk == desk.value, detail=f"desk = {desk.value}"),
        hypotheses=_count(
            session, Hypothesis, Hypothesis.desk == desk.value, detail=f"desk = {desk.value}"
        ),
        strategies=_count(
            session,
            Strategy,
            Strategy.desk == desk.value,
            detail=f"desk = {desk.value}",
        ),
        notes=spec.notes,
    )


@dataclass(frozen=True, slots=True)
class GraveyardView:
    """Killed research, at its true size. A full room, not a hidden tab."""

    rows: list[dict[str, Any]]
    refuted: Figure
    inconclusive: Figure
    underpowered: Figure
    shelved: Figure


def graveyard_view(session: Session) -> GraveyardView:
    dead = (
        HypothesisState.REFUTED,
        HypothesisState.INCONCLUSIVE,
        HypothesisState.UNDERPOWERED,
        HypothesisState.SHELVED,
        HypothesisState.ABANDONED_BUDGET,
    )
    rows = list(
        session.execute(
            sa.select(Hypothesis)
            .where(Hypothesis.state.in_([state.value for state in dead]))
            .order_by(Hypothesis.ref)
        ).scalars()
    )
    return GraveyardView(
        rows=[
            {
                "ref": row.ref,
                "claim": row.claim,
                "state": row.state,
                "family": row.family,
                "desk": row.desk or "—",
                "reason": row.verdict_reason,
            }
            for row in rows
        ],
        refuted=_state_count(session, HypothesisState.REFUTED),
        inconclusive=_state_count(session, HypothesisState.INCONCLUSIVE),
        underpowered=_state_count(session, HypothesisState.UNDERPOWERED),
        shelved=_state_count(session, HypothesisState.SHELVED),
    )


@dataclass(frozen=True, slots=True)
class KnowledgeView:
    trials: Figure
    lessons: Figure
    standing_rules: Figure
    corpora: list[dict[str, Any]]
    recent_lessons: list[dict[str, Any]]


def knowledge_view(session: Session) -> KnowledgeView:
    return KnowledgeView(
        trials=_count(session, CorpusTrial),
        lessons=_count(session, Lesson, Lesson.retired_at.is_(None), detail="not retired"),
        standing_rules=_count(
            session,
            Lesson,
            sa.and_(Lesson.standing_rule.is_(True), Lesson.retired_at.is_(None)),
            detail="standing_rule and not retired",
        ),
        corpora=[
            {
                "corpus": row.corpus,
                "claimed": Figure(
                    row.claimed_total, Source.table("corpus_reconciliations", row.corpus)
                ),
                "documented": Figure(
                    row.documented_total,
                    Source.table("corpus_reconciliations", row.corpus),
                ),
                "unallocated": Figure(
                    row.unallocated, Source.table("corpus_reconciliations", row.corpus)
                ),
                "reason": row.unallocated_reason,
                "reconciles": row.reconciles,
                "digest": row.digest,
            }
            for row in session.execute(sa.select(CorpusReconciliation)).scalars()
        ],
        recent_lessons=[
            {
                "ref": row.ref,
                "statement": row.statement,
                "standing_rule": row.standing_rule,
                "source_ref": row.source_ref,
            }
            for row in session.execute(
                sa.select(Lesson)
                .where(Lesson.retired_at.is_(None))
                .order_by(Lesson.created_at.desc())
                .limit(20)
            ).scalars()
        ],
    )


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    seq: int
    at: dt.datetime
    actor: str
    kind: str
    subject: str
    summary: str
    href: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def timeline(session: Session, limit: int = 80, since: int = 0) -> list[TimelineEntry]:
    """The company's day, as a projection of the event table.

    Ordered, actored, subjected — the ledger already holds all three, so this
    costs a query and invents nothing. It is the cheapest honest view in the
    station.
    """
    query = sa.select(Event).order_by(Event.seq.desc()).limit(limit)
    if since:
        query = sa.select(Event).where(Event.seq > since).order_by(Event.seq)
    rows = list(session.execute(query).scalars())
    if not since:
        rows.reverse()

    return [
        TimelineEntry(
            seq=row.seq,
            at=row.created_at,
            actor=row.actor,
            kind=row.kind,
            subject=row.subject or "—",
            summary=_summarise(row),
            href=_href_for(row.subject),
            payload=dict(row.payload or {}),
        )
        for row in rows
    ]


# ----------------------------------------------------------------- helpers


def _count(
    session: Session,
    table: Any,
    where: Any = None,
    *,
    detail: str = "",
) -> Figure:
    query = sa.select(sa.func.count()).select_from(table)
    if where is not None:
        query = query.where(where)
    value = int(session.execute(query).scalar_one())
    return Figure(value, Source.table(table.__tablename__, detail))


def _state_count(session: Session, state: HypothesisState) -> Figure:
    return _count(
        session, Hypothesis, Hypothesis.state == state.value, detail=f"state = {state.value}"
    )


def _coverage(session: Session, ref: str) -> tuple[str, ...]:
    from aurelis.agents.tables import AgentCoverage

    return tuple(
        session.execute(
            sa.select(AgentCoverage.charter_id)
            .where(AgentCoverage.agent_ref == ref)
            .order_by(AgentCoverage.charter_id)
        ).scalars()
    )


def _summarise(event: Event) -> str:
    """One line per event, built from its own payload.

    Deliberately mechanical. A summariser that paraphrased would be the
    station writing prose about the record, and prose is exactly where a
    reader stops being able to check.
    """
    payload = dict(event.payload or {})
    interesting = [
        f"{key}={value}"
        for key, value in payload.items()
        if isinstance(value, (str, int, bool)) and len(str(value)) <= 64
    ]
    return ", ".join(interesting[:4])


def _href_for(subject: str | None) -> str:
    if not subject:
        return ""
    prefix = subject.split("-")[0]
    return {
        "AG": f"/agent/{subject}",
        "MSN": f"/mission/{subject}",
        "MTG": f"/meeting/{subject}",
        "HYP": f"/hypothesis/{subject}",
    }.get(prefix, "")
