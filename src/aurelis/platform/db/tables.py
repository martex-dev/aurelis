"""The M0 schema.

Seven tables, and the shape of each is an argument.

``events`` is the spine. Everything the company does appends here, hash-chained
to its predecessor, and every other table is in some sense a projection of it.
It is append-only by trigger, not by convention.

``artifacts`` is the provenance anchor. A metric that cannot name the artifact
it was read out of does not enter the record, so this table is what makes
"nothing was typed" checkable.

``tasks``, ``budgets`` and ``cost_entries`` are the control plane: what work
exists, what it is allowed to spend, and what it actually spent. They live in
the same database as the ledger so that a task completing and the events
describing what it produced commit together or not at all.

``model_calls`` records every request to a language model, including cache
hits. Cost per accepted finding is a company metric from day one, and it
cannot be reconstructed later from logs nobody kept.

``ref_sequences`` allocates the human reference codes.

Tables for the corporation itself — agents, missions, meetings, hypotheses —
arrive with the layers that own them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from aurelis.core.enums import BudgetPeriod, TaskStatus
from aurelis.platform.db.types import GUID, Money, UtcDateTime

__all__ = [
    "APPEND_ONLY_TABLES",
    "Artifact",
    "Base",
    "Budget",
    "CostEntry",
    "Event",
    "ModelCall",
    "RefSequence",
    "ScheduledJob",
    "Task",
    "TaskDependency",
]


class Base(DeclarativeBase):
    """Declarative base with the project's type map."""

    type_annotation_map = {
        dt.datetime: UtcDateTime,
        Decimal: Money,
        uuid.UUID: GUID,
        dict[str, Any]: sa.JSON,
    }


class Event(Base):
    """One immutable record of something that happened.

    ``seq`` is a dense monotonic integer, not a timestamp, because the chain
    needs a total order and clocks do not provide one. Verification checks
    that sequence numbers are contiguous as well as that hashes link, since
    deleting a trailing run of events is the one edit a pure hash chain cannot
    detect.

    It is allocated explicitly rather than by autoincrement, because ``seq`` is
    part of the chain hash preimage: the row must arrive complete. An insert
    followed by an update would be refused by this table's own append-only
    trigger, which is the correct outcome and a good reminder that the rule
    applies to the code that wrote it too.
    """

    __tablename__ = "events"

    seq: Mapped[int] = mapped_column(
        sa.BigInteger().with_variant(sa.Integer, "sqlite"),
        primary_key=True,
        autoincrement=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True)

    actor: Mapped[str] = mapped_column(sa.String(64), index=True)
    """Who caused it. A reference code (``AG-0042``) or a control-plane actor."""

    kind: Mapped[str] = mapped_column(sa.String(64), index=True)
    subject: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    """What it was about, as a reference code. Null for company-wide events."""

    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    payload_hash: Mapped[str] = mapped_column(sa.String(64))
    prev_hash: Mapped[str | None] = mapped_column(sa.String(64))
    chain_hash: Mapped[str] = mapped_column(sa.String(64), index=True)

    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.Index("ix_events_subject_seq", "subject", "seq"),
        sa.Index("ix_events_kind_seq", "kind", "seq"),
    )


class Artifact(Base):
    """A stored blob, addressed by the hash of its content.

    Rows are never updated: storing content that already exists is a no-op
    returning the same hash. ``produced_by`` is free text at M0 and becomes a
    run reference once the engine layer exists.
    """

    __tablename__ = "artifacts"

    digest: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(64), index=True)
    media_type: Mapped[str] = mapped_column(sa.String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    produced_by: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)


class Task(Base):
    """A unit of work on the durable queue."""

    __tablename__ = "tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    kind: Mapped[str] = mapped_column(sa.String(64), index=True)
    assignee: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    """Reference code of the agent this is for. Null means any eligible worker."""

    subject: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    priority: Mapped[int] = mapped_column(default=100)
    """Lower runs first. Deliberately an integer rather than an enum so a
    scheduler can interleave without a migration."""

    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)

    status: Mapped[str] = mapped_column(sa.String(24), default=TaskStatus.QUEUED, index=True)
    allowance_usd: Mapped[Decimal | None] = mapped_column()
    allowance_tokens: Mapped[int | None] = mapped_column()

    budget_scope: Mapped[str | None] = mapped_column(sa.String(24))
    budget_scope_id: Mapped[str | None] = mapped_column(sa.String(64))

    budget_envelope: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    """Every scope this task's spend counts against, as checked at dispatch.

    Stored rather than re-derived because the envelope that was *checked* is
    the one the spend belongs to. Re-deriving it later would attribute work to
    whatever hierarchy exists then, and historical totals would quietly move.
    It also keeps the worker from having to know what a mission is."""

    claimed_by: Mapped[str | None] = mapped_column(sa.String(64))
    claimed_at: Mapped[dt.datetime | None] = mapped_column()
    finished_at: Mapped[dt.datetime | None] = mapped_column()

    result_digest: Mapped[str | None] = mapped_column(sa.String(64))
    failure_reason: Mapped[str | None] = mapped_column(sa.Text)

    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('queued','claimed','succeeded','failed','refused_budget','cancelled')",
            name="ck_tasks_status",
        ),
        sa.Index("ix_tasks_ready", "status", "priority", "created_at"),
    )


class TaskDependency(Base):
    """``task_ref`` cannot start until ``depends_on_ref`` has succeeded.

    A queue-level concept rather than a mission-level one, because the rule is
    about work rather than about the company: the researcher's task waits for
    the analyst's briefing whether or not either belongs to a mission.

    Two consequences worth stating. A task whose dependency has not finished is
    invisible to :meth:`TaskQueue.claim`, so nothing polls and no orchestrator
    is needed. And a task whose dependency *terminally failed* is cancelled
    rather than left waiting, because a chain that silently stalls forever is
    indistinguishable from a chain nobody started.
    """

    __tablename__ = "task_dependencies"

    task_ref: Mapped[str] = mapped_column(sa.String(24), primary_key=True, index=True)
    depends_on_ref: Mapped[str] = mapped_column(sa.String(24), primary_key=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column()

    __table_args__ = (
        sa.CheckConstraint("task_ref <> depends_on_ref", name="ck_task_not_self_dependent"),
    )


class Budget(Base):
    """An allowance at one scope.

    Money and tokens are budgeted separately because they are separately
    scarce. Under a subscription the money limit is meaningless and the token
    limit binds; under a metered API it is the other way round. Zero means
    "no cap at this level", which is different from a cap of zero.
    """

    __tablename__ = "budgets"

    budget_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(sa.String(24), index=True)
    scope_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    period: Mapped[str] = mapped_column(sa.String(16), default=BudgetPeriod.LIFETIME)
    period_key: Mapped[str] = mapped_column(sa.String(24), default="")
    """Which window this allowance covers, e.g. ``2026-09-04`` for a daily
    budget. Empty for lifetime budgets. Part of the uniqueness key so a new
    day opens a fresh allowance rather than resetting the old row."""

    limit_usd: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    limit_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column()

    __table_args__ = (
        sa.UniqueConstraint("scope", "scope_id", "period_key", name="uq_budget_scope_window"),
        sa.CheckConstraint(
            "scope IN ('company','department','mission','project','agent_day')",
            name="ck_budgets_scope",
        ),
    )


class CostEntry(Base):
    """One unit of spend, attributed to every scope it counts against.

    Denormalising the scopes onto the row rather than deriving them by join is
    a deliberate trade: spend must be answerable cheaply and identically at
    every level, and a join through a hierarchy that changes over time would
    make historical totals move.
    """

    __tablename__ = "cost_entries"

    entry_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    task_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    actor: Mapped[str] = mapped_column(sa.String(64), index=True)

    company_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    department_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    mission_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    agent_day_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)

    usd: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)

    reason: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)


class ModelCall(Base):
    """Every request to a language model, cached or not.

    ``cache_hit`` rows cost nothing and are still recorded, because the cache
    hit rate is one of the few cost levers that can be measured directly.
    """

    __tablename__ = "model_calls"

    call_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(sa.String(64), index=True)
    task_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    provider: Mapped[str] = mapped_column(sa.String(32), index=True)
    model: Mapped[str] = mapped_column(sa.String(64), index=True)
    tier: Mapped[str] = mapped_column(sa.String(8))

    request_hash: Mapped[str] = mapped_column(sa.String(64), index=True)
    response_hash: Mapped[str | None] = mapped_column(sa.String(64))

    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    usd: Mapped[Decimal] = mapped_column(default=Decimal("0"))

    cache_hit: Mapped[bool] = mapped_column(default=False)
    latency_ms: Mapped[int] = mapped_column(default=0)
    outcome: Mapped[str] = mapped_column(sa.String(24), default="ok")

    created_at: Mapped[dt.datetime] = mapped_column(index=True)


class ScheduledJob(Base):
    """A recurring platform job.

    Fixed-interval only at M0. The company's working day — briefings, standups,
    monitors, paper cycles — is built from these, and an interval covers all of
    it without a cron parser.
    """

    __tablename__ = "scheduled_jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    task_kind: Mapped[str] = mapped_column(sa.String(64))
    assignee: Mapped[str | None] = mapped_column(sa.String(24))
    """Which agent the fired task is for. Null means any eligible worker."""

    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)

    interval_seconds: Mapped[int] = mapped_column()
    enabled: Mapped[bool] = mapped_column(default=True)

    next_due_at: Mapped[dt.datetime] = mapped_column(index=True)
    last_fired_at: Mapped[dt.datetime | None] = mapped_column()
    fire_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column()

    __table_args__ = (
        sa.CheckConstraint("interval_seconds > 0", name="ck_jobs_interval_positive"),
    )


class RefSequence(Base):
    """Counters behind the human reference codes."""

    __tablename__ = "ref_sequences"

    prefix: Mapped[str] = mapped_column(sa.String(8), primary_key=True)
    next_value: Mapped[int] = mapped_column(default=1)


APPEND_ONLY_TABLES: tuple[str, ...] = ("events", "artifacts", "cost_entries", "model_calls")
"""Tables whose rows are facts about the past.

``UPDATE`` and ``DELETE`` are refused on these by trigger, in every dialect, so
the rule holds against raw SQL and not merely against this package.
"""
