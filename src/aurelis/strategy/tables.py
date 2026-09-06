"""The strategy record.

The shape of these tables is the milestone's argument. A design where a
strategy is a foreign key to a winning hypothesis would make the company a
selection engine: it would work until the corpus ran out and would never
produce anything nobody had already thought of.

So the centre of gravity is ``components`` — authored pieces with a stated
:class:`~aurelis.strategy.states.Origin` and a citation for it — and
``strategy_versions`` is a *composition* of them. "Did we create this?" becomes
a query over origins rather than a matter of opinion, and a version assembled
entirely from ``ADAPTED`` components reads honestly as inheritance rather than
invention.

``version_components`` is the join, and it carries the position and role of
each component in the composition, so the same signal can appear in two
strategies without either owning it.

``strategy_portability`` records what is known about a version on each of the
seven desks. Every desk except the one it was built on starts ``UNPROVEN``.
The inherited corpus was crypto-only; treating a crypto result as a market
regularity is precisely the mistake that record makes available.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base
from aurelis.strategy.states import Portability, StrategyState

__all__ = [
    "Component",
    "PromotionGate",
    "Strategy",
    "StrategyLineage",
    "StrategyPortability",
    "StrategyVersion",
    "VersionComponent",
]


class Component(Base):
    """One authored piece of a strategy, and where it came from.

    ``origin`` and ``origin_ref`` are both required by a CHECK. A component
    that cannot say where it came from is indistinguishable from one somebody
    copied, and the company's claim to have *created* an edge rests entirely on
    being able to tell those apart.
    """

    __tablename__ = "components"

    component_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    kind: Mapped[str] = mapped_column(sa.String(16), index=True)
    name: Mapped[str] = mapped_column(sa.String(96), index=True)
    spec: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    spec_digest: Mapped[str] = mapped_column(sa.String(64), index=True)

    rationale: Mapped[str] = mapped_column(sa.Text)
    """Why this should work, in the author's words, before it was tested. A
    component with no stated reasoning is a parameter somebody tried."""

    origin: Mapped[str] = mapped_column(sa.String(24), index=True)
    origin_ref: Mapped[str] = mapped_column(sa.String(48), index=True)
    """The meeting that invented it, the hypothesis it answers, the inherited
    trial it was adapted from, or the component it refines."""

    author: Mapped[str] = mapped_column(sa.String(24), index=True)
    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    """The market it was authored for. Not where it works — where it was
    written."""

    assumes: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """Structural assumptions: ``continuous_trading``, ``perpetual_funding``,
    ``short_selling``. Checked against a desk before the component is used
    there, so a 24/7 funding signal cannot silently be applied to a calendar
    market."""

    retired_at: Mapped[dt.datetime | None] = mapped_column()
    retired_reason: Mapped[str] = mapped_column(sa.Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "kind IN ('signal','filter','entry','exit','sizing')",
            name="ck_component_kind",
        ),
        sa.CheckConstraint(
            "origin IN ('invented','derived_from_failure','adapted','refined',"
            "'combined')",
            name="ck_component_origin",
        ),
        sa.CheckConstraint(
            "length(trim(origin_ref)) > 0",
            name="ck_component_cites_its_origin",
        ),
        sa.CheckConstraint(
            "length(trim(rationale)) > 0",
            name="ck_component_states_its_reasoning",
        ),
    )


class Strategy(Base):
    """A persistent research entity. Versioned, and never silently changed."""

    __tablename__ = "strategies"

    strategy_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    name: Mapped[str] = mapped_column(sa.String(120))
    thesis: Mapped[str] = mapped_column(sa.Text)
    """Why this should make money, stated in words a person can disagree
    with. Required at CANDIDATE."""

    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    state: Mapped[str] = mapped_column(
        sa.String(24), default=StrategyState.IDEA, index=True
    )
    current_version: Mapped[str | None] = mapped_column(sa.String(24))

    owner_agent: Mapped[str] = mapped_column(sa.String(24), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(index=True)
    state_reason: Mapped[str] = mapped_column(sa.Text, default="")
    retired_at: Mapped[dt.datetime | None] = mapped_column()
    retirement_reason: Mapped[str] = mapped_column(sa.Text, default="")


class StrategyVersion(Base):
    """One immutable composition.

    Once ``promoted_at`` is set the spec and its digest cannot change — a
    database trigger refuses the update. A material change is a new row at
    ``UNDER_REVIEW``, which is what stops a validated strategy from being
    quietly improved after the evidence was gathered.
    """

    __tablename__ = "strategy_versions"

    version_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    strategy_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    n: Mapped[int] = mapped_column()

    spec: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    spec_digest: Mapped[str] = mapped_column(sa.String(64), index=True)

    desk: Mapped[str] = mapped_column(sa.String(24), index=True)
    """The desk it was composed for. Behaviour anywhere else is a claim
    requiring evidence — see ``strategy_portability``."""

    universe: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    cost_model: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    constraints: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    risk_assumptions: Mapped[str] = mapped_column(sa.Text, default="")

    state: Mapped[str] = mapped_column(
        sa.String(24), default=StrategyState.UNDER_REVIEW, index=True
    )
    evidence: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    known_weaknesses: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """Stated by the authors, before review. A version claiming none is
    refused: every composition has a regime it does not survive, and one whose
    authors cannot name it has not looked."""

    supersedes: Mapped[str | None] = mapped_column(sa.String(24))
    change_reason: Mapped[str] = mapped_column(sa.Text, default="")
    material_change: Mapped[bool] = mapped_column(default=False)

    created_by: Mapped[str] = mapped_column(sa.String(24), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(index=True)
    promoted_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    promoted_by_meeting: Mapped[str | None] = mapped_column(sa.String(24))

    __table_args__ = (
        sa.UniqueConstraint("strategy_ref", "n", name="uq_version_number"),
        sa.CheckConstraint("n >= 1", name="ck_version_number_positive"),
    )


class VersionComponent(Base):
    """One component's place in one composition."""

    __tablename__ = "version_components"

    version_ref: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    component_ref: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    role: Mapped[str] = mapped_column(sa.String(16), index=True)
    position: Mapped[int] = mapped_column(default=0)
    weight: Mapped[Decimal | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column()


class StrategyLineage(Base):
    """How a version came to exist. Append-only.

    The answer to "did the agents create this, or select it?" is this table
    read in order. Each row names an act — composed, mutated, decomposed,
    ported — its author, and what it was done to.
    """

    __tablename__ = "strategy_lineage"

    entry_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    act: Mapped[str] = mapped_column(sa.String(24), index=True)
    parent_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    detail: Mapped[str] = mapped_column(sa.Text)
    author: Mapped[str] = mapped_column(sa.String(24), index=True)
    meeting_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(index=True)


class StrategyPortability(Base):
    """What is known about a version on one desk.

    A row per desk per version, so an unmeasured market is an explicit
    ``UNPROVEN`` rather than an absence somebody reads as fine. The inherited
    corpus covers one market of seven; this table is where that stops being
    invisible.
    """

    __tablename__ = "strategy_portability"

    version_ref: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    desk: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    status: Mapped[str] = mapped_column(
        sa.String(16), default=Portability.UNPROVEN, index=True
    )
    reason: Mapped[str] = mapped_column(sa.Text, default="")
    evidence_ref: Mapped[str | None] = mapped_column(sa.String(24))
    assessed_at: Mapped[dt.datetime | None] = mapped_column()

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('native','unproven','ported','refuted_here','inapplicable')",
            name="ck_portability_status",
        ),
        sa.CheckConstraint(
            "status = 'unproven' OR length(trim(reason)) > 0",
            name="ck_portability_claim_states_its_reason",
        ),
    )


class PromotionGate(Base):
    """One gate, registered before it is evaluated.

    ``registered_at`` predates ``evaluated_at`` and a trigger enforces it. A
    gate whose criterion could be written after the measurement is not a gate;
    it is a description of what happened.
    """

    __tablename__ = "promotion_gates"

    gate_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    gate: Mapped[str] = mapped_column(sa.String(2), index=True)

    criterion: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    criterion_digest: Mapped[str] = mapped_column(sa.String(64))
    owner_charter: Mapped[str] = mapped_column(sa.String(48))

    registered_at: Mapped[dt.datetime] = mapped_column(index=True)
    registered_by: Mapped[str] = mapped_column(sa.String(24))

    evaluated_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    evaluated_by: Mapped[str | None] = mapped_column(sa.String(24))
    passed: Mapped[bool | None] = mapped_column(index=True)
    observed: Mapped[str] = mapped_column(sa.Text, default="")
    evidence_ref: Mapped[str | None] = mapped_column(sa.String(64))

    __table_args__ = (
        sa.UniqueConstraint("version_ref", "gate", name="uq_one_gate_per_version"),
        sa.CheckConstraint(
            "gate IN ('A','B','C','D','E','F','G')", name="ck_gate_letter"
        ),
        sa.CheckConstraint(
            "(evaluated_at IS NULL) = (passed IS NULL)",
            name="ck_gate_result_travels_with_its_evaluation",
        ),
    )
