"""Controlled vocabularies for the M0 platform.

These are enums rather than free strings because each one is load-bearing for
something the platform enforces. Vocabularies for the corporation itself —
departments, desks, roles, hypothesis states — arrive with the layers that own
them; putting them here early would make ``core`` know about the company.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "Actor",
    "BudgetOutcome",
    "BudgetPeriod",
    "BudgetScope",
    "EventKind",
    "ModelTier",
    "TaskStatus",
]


class Actor(StrEnum):
    """Who caused an event, at platform granularity.

    ``SYSTEM`` is the deterministic control plane. Agents appear by their own
    reference code once the agent layer exists (M1); until then everything the
    platform does is honestly attributed to SYSTEM rather than to a placeholder
    identity.
    """

    SYSTEM = "system"
    OPERATOR = "operator"
    """A human acting through the CLI or the station. Distinguished from
    SYSTEM because "a person did this" is exactly what an audit wants to
    know."""


class EventKind(StrEnum):
    """Platform-level event vocabulary.

    Each layer adds its own kinds as it lands. Keeping them enumerated rather
    than free-text is what makes the timeline queryable and the station able to
    render an event it has never specifically been taught about.
    """

    # Lifecycle
    DATABASE_INITIALISED = "database.initialised"
    SCHEMA_MIGRATED = "schema.migrated"

    # Artifacts
    ARTIFACT_STORED = "artifact.stored"

    # Tasks
    TASK_ENQUEUED = "task.enqueued"
    TASK_CLAIMED = "task.claimed"
    TASK_SUCCEEDED = "task.succeeded"
    TASK_FAILED = "task.failed"
    TASK_REFUSED_BUDGET = "task.refused_budget"
    TASK_CANCELLED = "task.cancelled"

    # Budget
    BUDGET_OPENED = "budget.opened"
    BUDGET_SPENT = "budget.spent"
    BUDGET_EXHAUSTED = "budget.exhausted"

    # Model access
    MODEL_CALLED = "model.called"
    MODEL_CACHE_HIT = "model.cache_hit"
    MODEL_REFUSED = "model.refused"

    # Scheduling
    JOB_REGISTERED = "job.registered"
    JOB_FIRED = "job.fired"

    # The organization
    ORG_SEEDED = "org.seeded"
    DESK_OPENED = "desk.opened"
    AGENT_HIRED = "agent.hired"
    AGENT_ONBOARDED = "agent.onboarded"
    AGENT_STATE_CHANGED = "agent.state_changed"
    COVERAGE_GRANTED = "agent.coverage_granted"
    COVERAGE_REVOKED = "agent.coverage_revoked"

    # Missions
    MISSION_OPENED = "mission.opened"
    MISSION_STATE_CHANGED = "mission.state_changed"
    PROJECT_OPENED = "project.opened"
    PROJECT_STATE_CHANGED = "project.state_changed"
    KICKOFF_RECORDED = "mission.kickoff_recorded"
    RETROSPECTIVE_RECORDED = "mission.retrospective_recorded"

    # Meetings
    MEETING_CONVENED = "meeting.convened"
    MEETING_CLOSED = "meeting.closed"
    MEETING_UNPRODUCTIVE = "meeting.unproductive"
    """No decision, action item or objection. A metric on the Chair and on the
    meeting type, not a failure of any individual turn."""

    TURN_REFUSED = "meeting.turn_refused"
    """A speaker stated a figure nothing it was shown supports."""

    MIND_CHANGED = "meeting.mind_changed"
    OBJECTION_RAISED = "meeting.objection_raised"
    DECISION_RECORDED = "meeting.decision_recorded"
    FORECAST_SCORED = "meeting.forecast_scored"

    # Agent work
    TOOL_CALLED = "tool.called"
    OBSERVATION_RECORDED = "intel.observation_recorded"
    MESSAGE_POSTED = "comms.message_posted"
    CHANNEL_CREATED = "comms.channel_created"
    PERMISSION_DENIED = "agent.permission_denied"
    """An agent reached outside its scope. Recorded rather than only raised:
    this is exactly what an Agent Behavior Auditor samples for."""

    # Demonstration (M0 only — removed when real agents arrive in M1)
    DEMO_EXCHANGE = "demo.exchange"


class TaskStatus(StrEnum):
    """Where a queued unit of work stands.

    ``REFUSED_BUDGET`` is a terminal status rather than an exception because
    running out of money is a legitimate outcome for a line of work, and the
    record should say so. ``FAILED`` is terminal too: a worker that could not
    produce a valid artifact has told us something, and retrying it into
    success would erase the only signal.
    """

    QUEUED = "queued"
    CLAIMED = "claimed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED_BUDGET = "refused_budget"
    CANCELLED = "cancelled"


TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.REFUSED_BUDGET,
        TaskStatus.CANCELLED,
    }
)


class BudgetScope(StrEnum):
    """The levels money is budgeted at, outermost first.

    Ordering matters: a refusal names the innermost level that bound it, so an
    operator is told which knob to turn rather than merely that something ran
    out.
    """

    COMPANY = "company"
    DEPARTMENT = "department"
    MISSION = "mission"
    PROJECT = "project"
    AGENT_DAY = "agent_day"


BUDGET_SCOPE_ORDER: tuple[BudgetScope, ...] = (
    BudgetScope.COMPANY,
    BudgetScope.DEPARTMENT,
    BudgetScope.MISSION,
    BudgetScope.PROJECT,
    BudgetScope.AGENT_DAY,
)


class BudgetPeriod(StrEnum):
    """Whether an allowance refills."""

    LIFETIME = "lifetime"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class BudgetOutcome(StrEnum):
    ALLOWED = "allowed"
    REFUSED = "refused"


class ModelTier(StrEnum):
    """How much model a piece of work is worth.

    Tier is assigned by role and seniority, which is how cost tracks
    importance. ``NONE`` is a real tier and covers most of the company: every
    deterministic officer, every statistic, every scheduled check.
    """

    NONE = "none"
    LOW = "low"
    MID = "mid"
    HIGH = "high"
