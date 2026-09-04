"""Agents as rows.

An agent is a database row, not a class. That is the whole reason the company
can grow from seventeen to a hundred without the runtime changing: hiring is an
``INSERT``, and a fission is an insert plus a coverage transfer.

``AgentCoverage`` is the join that carries authority. An agent's permissions are
the union of the scopes of the charters it covers, and the scope-guarded insert
triggers check exactly that join. Moving a charter from one agent to another
moves the authority with it, atomically, which is what makes fission safe.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["Agent", "AgentCoverage", "AgentState", "ToolCall"]

from enum import StrEnum


class AgentState(StrEnum):
    """Where an agent is in its working life.

    ``ONBOARDING`` is a real state, not a formality: a newly hired agent runs
    the training-scenario suite for its charters before it touches live
    research (ADR-0005). ``RETIRED`` preserves everything the agent produced —
    a retired agent's outputs stay in the record permanently.
    """

    HIRED = "hired"
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    WORKING = "working"
    IN_MEETING = "in_meeting"
    BLOCKED = "blocked"
    RETRAINING = "retraining"
    SUSPENDED = "suspended"
    RETIRED = "retired"


WORKABLE_STATES = frozenset({AgentState.ACTIVE, AgentState.WORKING})


class Agent(Base):
    """One member of staff."""

    __tablename__ = "agents"

    agent_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    """``AG-0042``. What colleagues cite, and the key the scope triggers use."""

    handle: Mapped[str] = mapped_column(sa.String(32), index=True)
    """Short working name: ``INTEL``, ``CRITIC``, ``TA-CRYPTO``."""

    department: Mapped[str] = mapped_column(sa.String(48), index=True)
    desk: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    team: Mapped[str | None] = mapped_column(sa.String(32), index=True)
    seniority: Mapped[str] = mapped_column(sa.String(16))
    tier: Mapped[str] = mapped_column(sa.String(8))
    """Resolved model tier: the highest of the charters held. Cost follows
    seniority, which is how spend tracks importance."""

    state: Mapped[str] = mapped_column(sa.String(16), default=AgentState.HIRED, index=True)

    daily_token_budget: Mapped[int] = mapped_column(default=0)
    daily_usd_budget: Mapped[str] = mapped_column(sa.String(24), default="0")
    """Stored as text for the same reason money is elsewhere: exactness."""

    hired_at: Mapped[dt.datetime] = mapped_column(index=True)
    onboarded_at: Mapped[dt.datetime | None] = mapped_column()
    suspended_at: Mapped[dt.datetime | None] = mapped_column()
    retired_at: Mapped[dt.datetime | None] = mapped_column()

    hired_by: Mapped[str] = mapped_column(sa.String(64), default="operator")
    """Who authorised the hire. Becomes an OrgChange reference at M11, when
    the company starts hiring itself."""

    note: Mapped[str] = mapped_column(sa.Text, default="")

    __table_args__ = (
        sa.CheckConstraint(
            "state IN ('hired','onboarding','active','working','in_meeting','blocked',"
            "'retraining','suspended','retired')",
            name="ck_agents_state",
        ),
    )


class AgentCoverage(Base):
    """Which charters an agent currently holds.

    The row that carries authority. A launch generalist holds nine of these; a
    Stage-4 specialist holds one. Nothing else about the agent changes when it
    splits.
    """

    __tablename__ = "agent_coverage"

    agent_ref: Mapped[str] = mapped_column(
        sa.ForeignKey("agents.ref", ondelete="CASCADE"), primary_key=True, index=True
    )
    charter_id: Mapped[str] = mapped_column(
        sa.ForeignKey("org_charters.charter_id"), primary_key=True, index=True
    )
    granted_at: Mapped[dt.datetime] = mapped_column()
    granted_by: Mapped[str] = mapped_column(sa.String(64), default="operator")


class ToolCall(Base):
    """Every capability invocation, with its cost.

    "What did this agent actually do today?" has to be a query rather than an
    investigation, so tool calls are recorded the same way model calls are —
    including the ones that failed, because a refused tool call is exactly the
    kind of thing an Agent Behavior Auditor is looking for.
    """

    __tablename__ = "tool_calls"

    call_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    task_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    tool: Mapped[str] = mapped_column(sa.String(48), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)

    outcome: Mapped[str] = mapped_column(sa.String(16), default="ok", index=True)
    """``ok`` | ``refused`` | ``failed``. A refusal is a recorded outcome."""

    detail: Mapped[str] = mapped_column(sa.Text, default="")
    result_digest: Mapped[str | None] = mapped_column(sa.String(64))
    duration_ms: Mapped[int] = mapped_column(default=0)
    usd: Mapped[str] = mapped_column(sa.String(24), default="0")

    created_at: Mapped[dt.datetime] = mapped_column(index=True)
