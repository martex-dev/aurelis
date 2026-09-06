"""The risk and trading record.

Three facts are enforced by the database rather than by discipline, because a
risk function that depends on everyone remembering to consult it is not an
authority — it is a convention.

1. A ``TradeProposal`` without a matching ``RiskAssessment`` cannot become a
   ``TradeApproval``. Foreign key *and* trigger: the FK stops a dangling
   reference, the trigger stops an approval whose assessment belongs to a
   different proposal.
2. ``RiskAssessment`` is written only by risk roles — the write-scope guard
   installed in M1 already does this, and M8 adds the table it applies to.
3. An ``Order`` requires an ``approval_id``. Orders arrive with paper trading
   in M9; the column and its constraint exist now so the boundary is in place
   before anything can cross it.

``desired_exposure``, ``allowed_exposure`` and ``final_target`` are all
persisted on every proposal, always. That is what makes "Risk allowed the full
size" and "Risk was never asked" different rows instead of the same silence.

The kill latch is inherited in spirit from martex-quant's guard: a tripped
latch is **never cleared by code**. There is no function in this package that
clears one, which is not an oversight — clearing it is a deliberate human act
after understanding what died.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = [
    "KillLatch",
    "RiskAssessment",
    "RiskLimit",
    "TradeApproval",
    "TradeProposal",
]


class RiskLimit(Base):
    """A bound Risk has imposed. Scoped, versioned, and never deleted."""

    __tablename__ = "risk_limits"

    limit_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(sa.String(16), index=True)
    scope_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    metric: Mapped[str] = mapped_column(sa.String(32), index=True)
    bound: Mapped[Decimal] = mapped_column()

    reason: Mapped[str] = mapped_column(sa.Text)
    set_by: Mapped[str] = mapped_column(sa.String(24), index=True)
    set_at: Mapped[dt.datetime] = mapped_column(index=True)
    lifted_at: Mapped[dt.datetime | None] = mapped_column()
    lifted_reason: Mapped[str] = mapped_column(sa.Text, default="")

    __table_args__ = (
        sa.CheckConstraint(
            "scope IN ('company','desk','strategy','version','factor')",
            name="ck_risk_limit_scope",
        ),
    )


class TradeProposal(Base):
    """What a strategy asked for, what Risk permitted, what was settled on.

    All three are columns and all three are always written. A schema that
    stored only the final number could not distinguish a proposal Risk cut in
    half from one it never saw.
    """

    __tablename__ = "trade_proposals"

    proposal_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    portfolio_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    version_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    symbol: Mapped[str] = mapped_column(sa.String(32), index=True)
    side: Mapped[str] = mapped_column(sa.String(8))

    desired_exposure: Mapped[Decimal] = mapped_column()
    allowed_exposure: Mapped[Decimal | None] = mapped_column()
    """Null until Risk has assessed. Not zero — an unassessed proposal and a
    vetoed one are different things."""

    final_target: Mapped[Decimal | None] = mapped_column()

    rationale: Mapped[str] = mapped_column(sa.Text)
    evidence_refs: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    proposed_by: Mapped[str] = mapped_column(sa.String(24), index=True)
    proposed_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_proposal_side"),
        sa.CheckConstraint(
            "desired_exposure >= 0", name="ck_proposal_desired_not_negative"
        ),
    )


class RiskAssessment(Base):
    """One risk decision, recorded whether or not it changed anything."""

    __tablename__ = "risk_assessments"

    assessment_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    proposal_ref: Mapped[str] = mapped_column(
        sa.ForeignKey("trade_proposals.ref"), index=True
    )

    assessor: Mapped[str] = mapped_column(sa.String(24), index=True)
    desired_exposure: Mapped[Decimal] = mapped_column()
    allowed_exposure: Mapped[Decimal] = mapped_column()
    decision: Mapped[str] = mapped_column(sa.String(8), index=True)
    limits_applied: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    reason: Mapped[str] = mapped_column(sa.Text)
    assessed_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "decision IN ('allow','shrink','veto','halt')", name="ck_risk_decision"
        ),
        sa.CheckConstraint(
            "allowed_exposure >= 0", name="ck_allowed_not_negative"
        ),
        sa.CheckConstraint(
            "decision <> 'veto' OR allowed_exposure = 0",
            name="ck_veto_allows_nothing",
        ),
        sa.CheckConstraint(
            "decision <> 'allow' OR allowed_exposure = desired_exposure",
            name="ck_allow_means_the_full_size",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_risk_decision_states_its_reason"
        ),
    )


class TradeApproval(Base):
    """Permission to execute. Requires an assessment of *this* proposal."""

    __tablename__ = "trade_approvals"

    approval_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    proposal_ref: Mapped[str] = mapped_column(
        sa.ForeignKey("trade_proposals.ref"), index=True
    )
    assessment_ref: Mapped[str] = mapped_column(
        sa.ForeignKey("risk_assessments.ref"), index=True
    )

    final_target: Mapped[Decimal] = mapped_column()
    approved_by: Mapped[str] = mapped_column(sa.String(24), index=True)
    approved_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint("final_target >= 0", name="ck_approval_target_not_negative"),
    )


class KillLatch(Base):
    """A tripped kill switch. Latched, and never cleared by code.

    No function in this package sets ``cleared_at``. That is deliberate: a
    latch a program can clear is a pause, and the whole value of a latch is
    that a human has to look at what died before anything resumes.
    """

    __tablename__ = "kill_latches"

    latch_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(sa.String(16), index=True)
    scope_id: Mapped[str] = mapped_column(sa.String(48), index=True)

    tripwire: Mapped[str] = mapped_column(sa.String(48))
    """Which preregistered rule fired. A latch with no named rule would be
    somebody's judgement wearing a mechanism's clothes."""

    observed: Mapped[str] = mapped_column(sa.String(64))
    threshold: Mapped[str] = mapped_column(sa.String(64))
    detail: Mapped[str] = mapped_column(sa.Text)
    latched_at: Mapped[dt.datetime] = mapped_column(index=True)

    cleared_at: Mapped[dt.datetime | None] = mapped_column()
    cleared_by: Mapped[str | None] = mapped_column(sa.String(64))
    """A human's name, entered outside this package. Never written by Aurelis."""
