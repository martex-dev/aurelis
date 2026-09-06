"""Org metrics: what the company can actually measure about itself.

Every metric here is computed from rows the company already writes — the task
queue, the ledger, forecasts, training runs, coverage. Nothing is estimated and
nothing is a proxy dressed as a measurement.

**A metric that cannot be computed is ``None``, never zero.** This is the same
distinction the station's ``Figure`` type enforces, and it matters more here
than anywhere, because a zero is a *reason to split a role*. An Intelligence
charter with no outputs in thirty days is starved and someone should be hired
for it; an Intelligence charter whose outputs the record cannot attribute is a
gap in the instrumentation, and hiring for it would be acting on the absence of
a measurement.

That distinction is why ``breadth`` exists and is the first trigger the company
fires on itself. AG-0004 stands in for nine Intelligence charters, so no
measurement about any single one of them is attributable to it — and the honest
conclusion is not "those charters are idle" but "we cannot tell, and that is
the reason to split."
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent, AgentCoverage, AgentState, ToolCall
from aurelis.core.enums import TaskStatus
from aurelis.meetings.tables import Forecast, MeetingObjection
from aurelis.org.charters import CHARTERS
from aurelis.platform.db.tables import Task
from aurelis.research.tables import Finding
from aurelis.training.tables import TrainingRun

__all__ = [
    "COMPANY",
    "METRICS",
    "AgentMetrics",
    "Reading",
    "agent_metrics",
    "charter_starvation",
    "company_metrics",
    "overlap",
    "read_metric",
]

COMPANY = "AURELIS"

METRICS: dict[str, str] = {
    "backlog_depth": "open tasks assigned to this agent",
    "backlog_age_hours": "age of the oldest open task assigned to this agent",
    "throughput": "tasks this agent has completed",
    "breadth": "charters this agent stands in for",
    "attributable_charters": "charters whose outputs could be told apart",
    "calibration": "mean Brier score over this agent's scored forecasts",
    "scenario_catch_rate": "catch rate on the training suite",
    "objections_raised": "objections this agent has authored",
    "findings": "findings this agent has authored",
    "tool_calls": "capability invocations",
    "refusal_rate": "share of tool calls the permission system refused",
    "starved_charters": "charter areas with no attributable output",
    "agents_active": "agents in a working state",
    "charters_per_agent": "mean breadth across active agents",
}
"""Every metric the company may predict a change in.

A closed registry, because an ``OrgChange`` predicts a named metric and a
prediction naming something nobody can compute is not falsifiable. Adding a
metric here is how the company becomes able to make a new kind of prediction
about itself.
"""


@dataclass(frozen=True, slots=True)
class Reading:
    """One metric, or an honest statement that it could not be taken."""

    metric: str
    value: Decimal | None
    detail: str

    @property
    def measurable(self) -> bool:
        return self.value is not None

    def as_payload(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": None if self.value is None else str(self.value),
            "detail": self.detail,
        }

    def describe(self) -> str:
        if self.value is None:
            return f"{self.metric}: NOT MEASURABLE — {self.detail}"
        return f"{self.metric}: {self.value} ({self.detail})"


def _reading(metric: str, value: Decimal | int | None, detail: str) -> Reading:
    if value is None:
        return Reading(metric, None, detail)
    return Reading(metric, Decimal(value), detail)


@dataclass(frozen=True, slots=True)
class AgentMetrics:
    """Everything measurable about one agent, at one moment."""

    agent_ref: str
    handle: str
    readings: tuple[Reading, ...]

    def get(self, metric: str) -> Reading:
        for reading in self.readings:
            if reading.metric == metric:
                return reading
        raise KeyError(
            f"no org metric {metric!r}; the registry holds {sorted(METRICS)}"
        )

    def value(self, metric: str) -> Decimal | None:
        return self.get(metric).value

    def as_payload(self) -> dict[str, Any]:
        return {
            "agent_ref": self.agent_ref,
            "handle": self.handle,
            "readings": [r.as_payload() for r in self.readings],
        }


def agent_metrics(
    session: Session, agent_ref: str, *, now: dt.datetime | None = None
) -> AgentMetrics:
    """Measure one agent from the record."""
    row = session.execute(
        sa.select(Agent).where(Agent.ref == agent_ref)
    ).scalar_one_or_none()
    if row is None:
        raise KeyError(f"no agent {agent_ref!r}")

    coverage = tuple(
        session.execute(
            sa.select(AgentCoverage.charter_id)
            .where(AgentCoverage.agent_ref == agent_ref)
            .order_by(AgentCoverage.charter_id)
        ).scalars()
    )

    open_tasks = list(
        session.execute(
            sa.select(Task).where(
                Task.assignee == agent_ref,
                Task.status.in_((TaskStatus.QUEUED, TaskStatus.CLAIMED)),
            )
        ).scalars()
    )
    done = session.execute(
        sa.select(sa.func.count())
        .select_from(Task)
        .where(Task.assignee == agent_ref, Task.status == TaskStatus.SUCCEEDED)
    ).scalar_one()

    oldest: Decimal | None = None
    if open_tasks:
        moment = now or max(t.created_at for t in open_tasks)
        ages = [
            (moment - t.created_at).total_seconds() / 3600
            for t in open_tasks
            if t.created_at is not None
        ]
        if ages:
            oldest = Decimal(str(round(max(ages), 2)))

    calls = session.execute(
        sa.select(sa.func.count())
        .select_from(ToolCall)
        .where(ToolCall.agent_ref == agent_ref)
    ).scalar_one()
    refused = session.execute(
        sa.select(sa.func.count())
        .select_from(ToolCall)
        .where(ToolCall.agent_ref == agent_ref, ToolCall.outcome == "refused")
    ).scalar_one()

    briers = [
        Decimal(str(score))
        for score in session.execute(
            sa.select(Forecast.brier).where(
                Forecast.agent_ref == agent_ref, Forecast.brier.is_not(None)
            )
        ).scalars()
        if score is not None
    ]

    training = session.execute(
        sa.select(TrainingRun)
        .where(TrainingRun.agent_ref == agent_ref)
        .order_by(TrainingRun.measured_at.desc(), TrainingRun.ref.desc())
        .limit(1)
    ).scalar_one_or_none()

    objections = session.execute(
        sa.select(sa.func.count())
        .select_from(MeetingObjection)
        .where(MeetingObjection.author == agent_ref)
    ).scalar_one()
    findings = session.execute(
        sa.select(sa.func.count())
        .select_from(Finding)
        .where(Finding.author == agent_ref)
    ).scalar_one()

    readings = (
        _reading("backlog_depth", len(open_tasks), f"{len(open_tasks)} open"),
        _reading(
            "backlog_age_hours",
            oldest,
            "oldest open task" if oldest is not None else "no open tasks to age",
        ),
        _reading("throughput", done, f"{done} completed"),
        _reading("breadth", len(coverage), f"stands in for {len(coverage)} charters"),
        # The honest one, and a genuine count rather than a flag. An agent
        # holding one charter has outputs attributable to it; an agent holding
        # nine has **zero** attributable charters -- a measured zero, not a
        # gap, because the record really does say that none of its outputs can
        # be placed. Only an agent holding nothing is unmeasurable here.
        #
        # It was ``None`` for every generalist in the first version, which made
        # it useless as a prediction target: a change could not move it from
        # unmeasurable to unmeasurable and the verdict was always
        # ``UNMEASURABLE``. A metric a change cannot move is not a metric.
        _reading(
            "attributable_charters",
            None if not coverage else (1 if len(coverage) == 1 else 0),
            "holds no charters"
            if not coverage
            else "one charter, so its outputs are attributable"
            if len(coverage) == 1
            else f"stands in for {len(coverage)} charters, so none of its "
            "outputs can be attributed to any one of them",
        ),
        _reading(
            "calibration",
            (sum(briers, Decimal(0)) / len(briers)).quantize(Decimal("0.0001"))
            if briers
            else None,
            f"mean of {len(briers)} scored forecasts"
            if briers
            else "no forecast this agent made has been scored",
        ),
        _reading(
            "scenario_catch_rate",
            Decimal(training.catch_rate)
            if training is not None and training.catch_rate is not None
            else None,
            f"training run {training.ref}"
            if training is not None and training.catch_rate is not None
            else "no settled question in this agent's specialty",
        ),
        _reading("objections_raised", objections, f"{objections} authored"),
        _reading("findings", findings, f"{findings} authored"),
        _reading("tool_calls", calls, f"{calls} invocations"),
        _reading(
            "refusal_rate",
            (Decimal(refused) / Decimal(calls)).quantize(Decimal("0.0001"))
            if calls
            else None,
            f"{refused} of {calls} refused" if calls else "no tool calls to divide by",
        ),
    )
    return AgentMetrics(agent_ref=row.ref, handle=row.handle, readings=readings)


def charter_starvation(session: Session) -> dict[str, str]:
    """Charter areas whose outputs the record cannot tell apart, and why.

    Returns every charter mapped to the reason it is or is not attributable.
    A charter held by a generalist is **not** reported as starved: it is
    reported as unattributable, which is a different problem with a different
    fix.
    """
    holders: dict[str, str] = {
        str(charter_id): str(agent_ref)
        for charter_id, agent_ref in session.execute(
            sa.select(AgentCoverage.charter_id, AgentCoverage.agent_ref)
        ).all()
    }
    breadth: dict[str, int] = {}
    for agent_ref in holders.values():
        breadth[agent_ref] = breadth.get(agent_ref, 0) + 1

    report: dict[str, str] = {}
    for charter_id in CHARTERS:
        holder = holders.get(charter_id)
        if holder is None:
            report[charter_id] = "ORPHANED — nobody holds this charter"
        elif breadth.get(holder, 0) > 1:
            report[charter_id] = (
                f"unattributable — {holder} stands in for "
                f"{breadth[holder]} charters"
            )
        else:
            report[charter_id] = f"attributable to {holder}"
    return report


def overlap(session: Session, left: str, right: str) -> Reading:
    """How far two agents' authority duplicates each other.

    Coverage overlap, not output overlap. Two agents holding disjoint charters
    have no authority in common by construction — a charter has one owner — so
    this reads zero for every pair in the launch roster, and it is reported as
    a measured zero rather than left out. Output similarity needs a corpus of
    comparable artifacts per agent, which the company does not have yet, and
    inventing a number for it is exactly what this module refuses to do.
    """
    def held(ref: str) -> set[str]:
        return set(
            session.execute(
                sa.select(AgentCoverage.charter_id).where(
                    AgentCoverage.agent_ref == ref
                )
            ).scalars()
        )

    a, b = held(left), held(right)
    if not a or not b:
        return Reading(
            "output_overlap", None, f"{left} or {right} holds no charters"
        )
    shared = a & b
    union = a | b
    return Reading(
        "output_overlap",
        (Decimal(len(shared)) / Decimal(len(union))).quantize(Decimal("0.0001")),
        f"{len(shared)} charters in common of {len(union)}",
    )


def company_metrics(session: Session) -> tuple[Reading, ...]:
    """The whole company, in a handful of numbers."""
    active = list(
        session.execute(
            sa.select(Agent).where(
                Agent.state.notin_((AgentState.RETIRED, AgentState.SUSPENDED))
            )
        ).scalars()
    )
    starvation = charter_starvation(session)
    orphaned = [c for c, why in starvation.items() if why.startswith("ORPHANED")]
    unattributable = [c for c, why in starvation.items() if why.startswith("unattrib")]

    held = session.execute(sa.select(sa.func.count()).select_from(AgentCoverage)).scalar_one()
    return (
        _reading("agents_active", len(active), f"{len(active)} not retired or suspended"),
        _reading(
            "charters_per_agent",
            (Decimal(held) / Decimal(len(active))).quantize(Decimal("0.01"))
            if active
            else None,
            f"{held} charters over {len(active)} agents"
            if active
            else "nobody is employed",
        ),
        _reading(
            "starved_charters",
            len(orphaned),
            f"{len(orphaned)} orphaned, {len(unattributable)} held by a "
            "generalist and therefore unattributable",
        ),
    )


def read_metric(
    session: Session, subject: str, metric: str, *, now: dt.datetime | None = None
) -> Reading:
    """One named metric for one subject. What a prediction is checked against."""
    if metric not in METRICS:
        raise KeyError(
            f"no org metric {metric!r}; a change may only predict a metric the "
            f"company can compute. The registry holds {sorted(METRICS)}"
        )
    if subject == COMPANY:
        for reading in company_metrics(session):
            if reading.metric == metric:
                return reading
        raise KeyError(f"{metric!r} is an agent metric, not a company one")
    return agent_metrics(session, subject, now=now).get(metric)
