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

    # Training
    SCENARIO_SUITE_RUN = "training.suite_run"
    AGENT_SCORED = "training.agent_scored"
    ONBOARDING_REFUSED = "training.onboarding_refused"
    PLAYBOOK_REGRESSED = "training.playbook_regressed"

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

    # Research
    HYPOTHESIS_PROPOSED = "research.hypothesis_proposed"
    HYPOTHESIS_STATE_CHANGED = "research.hypothesis_state_changed"
    REGISTRATION_LOCKED = "research.registration_locked"
    """The preregistration is hashed and frozen. Nothing may run before this."""

    RUN_COMPLETED = "research.run_completed"
    RUN_FAILED = "research.run_failed"
    VERDICT_DERIVED = "research.verdict_derived"
    """Computed from the registered criteria by a pure function. No model
    chose it."""

    REPLICATION_RECORDED = "research.replication_recorded"
    VERDICT_OVERTURNED = "research.verdict_overturned"
    """A confirmed result was refuted by a later measurement. Its own kind,
    because a corpus that quietly rewrote conclusions would be worse than one
    that never revised them."""

    # Strategy, portfolio and risk
    COMPONENT_AUTHORED = "strategy.component_authored"
    """An agent wrote a piece of a strategy, with a cited origin. The event
    the company's claim to have *created* an edge rests on."""

    STRATEGY_OPENED = "strategy.opened"
    STRATEGY_VERSION_COMPOSED = "strategy.version_composed"
    STRATEGY_STATE_CHANGED = "strategy.state_changed"
    GATE_REGISTERED = "strategy.gate_registered"
    """A promotion criterion, fixed before it was evaluated."""

    GATE_EVALUATED = "strategy.gate_evaluated"
    VERSION_PROMOTED = "strategy.version_promoted"
    PORTABILITY_ASSESSED = "strategy.portability_assessed"
    """What is known about a version on a desk other than its own. The corpus
    is crypto-only; this is where that stops being invisible."""

    PORTFOLIO_OPENED = "portfolio.opened"
    ALLOCATION_DECIDED = "portfolio.allocation_decided"
    EXPOSURE_SNAPSHOT = "portfolio.exposure_snapshot"

    RISK_ASSESSED = "risk.assessed"
    """Recorded even when Risk changed nothing, so "Risk allowed it" and "Risk
    was never consulted" are different rows rather than the same silence."""

    RISK_LIMIT_SET = "risk.limit_set"
    TRADE_PROPOSED = "trading.proposed"
    TRADE_APPROVED = "trading.approved"
    TRADE_REFUSED = "trading.refused"
    ORDER_SUBMITTED = "trading.order_submitted"
    ORDER_FILLED = "trading.order_filled"
    ORDER_REJECTED = "trading.order_rejected"
    """A broker refused. Recorded rather than raised: a rejection is
    information about the venue, the instruction or the assumed price."""

    POSITION_CHANGED = "trading.position_changed"
    POST_TRADE_ANALYSED = "trading.post_trade_analysed"
    GAP_MEASURED = "trading.gap_measured"
    """Backtest expectation against what paper trading produced. The only
    measurement where reality gets a vote."""

    PAPER_CYCLE_RAN = "trading.paper_cycle_ran"
    ALERT_RAISED = "ops.alert_raised"
    ALERT_ACKNOWLEDGED = "ops.alert_acknowledged"
    ALERT_RESOLVED = "ops.alert_resolved"
    KILL_LATCHED = "risk.kill_latched"
    """Execution stopped and latched. Never cleared by code."""

    # Institutional memory
    CORPUS_IMPORTED = "memory.corpus_imported"
    """History arrived from another system, with its own figures preserved."""

    CORPUS_RECONCILED = "memory.corpus_reconciled"
    """An import's claimed totals were checked against what its documents
    account for. The gap is carried on the event, because an import that
    quietly made its numbers add up would be presenting a reconstruction as a
    verified figure."""

    KNOWLEDGE_LINKED = "memory.knowledge_linked"
    LESSON_RECORDED = "memory.lesson_recorded"
    LESSON_RETIRED = "memory.lesson_retired"
    PRIOR_ART_SEARCHED = "memory.prior_art_searched"
    """Recorded even when nothing was found, so "did anyone check?" is a query
    rather than a matter of trust."""

    VAULT_EXPORTED = "memory.vault_exported"

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
