"""The company's structure, with a version history.

An ``OrgChange`` is to the org chart what a ``Registration`` is to an
experiment: the prediction is written down and hashed **before** the decision,
and the outcome is recorded against it afterwards whichever way it comes out.
That is the whole reason this table exists rather than the company simply
hiring people. Without it, "we split Intelligence and things got better" is a
sentence somebody remembers; with it, it is a row with a locked prediction, a
measured before, a measured after, and a verdict that is sometimes ``worse``.

``predicted_*`` and ``measurement_plan`` are covered by ``locked_digest``. A
trigger refuses to change any of them once the lock is set, so the prediction
cannot be quietly re-aimed at whatever the metric happened to do.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.orgdev.states import OrgChangeState
from aurelis.platform.db.tables import Base

__all__ = ["CoverageTransfer", "OrgChange", "OrgExperiment", "OrgMetricSnapshot"]


class OrgChange(Base):
    """One proposed change to the company's own structure."""

    __tablename__ = "org_changes"

    change_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    kind: Mapped[str] = mapped_column(sa.String(16), index=True)
    state: Mapped[str] = mapped_column(
        sa.String(16), default=OrgChangeState.DRAFT, index=True
    )

    subject_agent: Mapped[str] = mapped_column(sa.String(24), index=True)
    """The agent the change is about. For a fission, the one being split."""

    counterpart_agent: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    """For a fusion, the agent being merged into. Null otherwise."""

    charters: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    """The charter areas that move. Empty for a retrain."""

    new_handle: Mapped[str | None] = mapped_column(sa.String(32))

    trigger: Mapped[str] = mapped_column(sa.String(32), index=True)
    trigger_evidence: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    """The measurement that fired the trigger, with the value and the
    threshold. A proposal without one is a hunch with a form around it."""

    justification: Mapped[str] = mapped_column(sa.Text, default="")

    predicted_metric: Mapped[str] = mapped_column(sa.String(48))
    predicted_direction: Mapped[str] = mapped_column(sa.String(8))
    """``up`` or ``down``. Which way the metric is expected to move."""

    predicted_magnitude: Mapped[str] = mapped_column(sa.String(24))
    """Stored as text, exactly like money and every other exact decimal here —
    and carrying the same trap, so every comparison on it casts first."""

    measurement_plan: Mapped[str] = mapped_column(sa.Text, default="")
    measure_after_days: Mapped[int] = mapped_column(default=7)

    locked_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    locked_digest: Mapped[str | None] = mapped_column(sa.String(64))
    """Covers the prediction and the plan. Set once, never changed."""

    proposed_by: Mapped[str] = mapped_column(sa.String(24), index=True)
    """The Org Development Lead. An agent may not propose a change to its own
    record, and a trigger enforces it."""

    decided_by: Mapped[str | None] = mapped_column(sa.String(24))
    decision_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    meeting_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    """The Board meeting that settled it. An applied change with no meeting
    behind it would be an unreviewed edit to the org chart.

    The CHECK covers ``measured`` as well as ``applied``: it named only the
    latter at first, so once a change had been measured its meeting could be
    cleared and the constraint said nothing. A guarantee that lapses one state
    later is not a guarantee."""

    baseline: Mapped[str | None] = mapped_column(sa.String(24))
    """The metric's value when the change was applied, read at that moment
    rather than reconstructed later."""

    realised: Mapped[str | None] = mapped_column(sa.String(24))
    effect: Mapped[str | None] = mapped_column(sa.String(16), index=True)
    effect_detail: Mapped[str] = mapped_column(sa.Text, default="")

    proposed_at: Mapped[dt.datetime] = mapped_column(index=True)
    applied_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    measured_at: Mapped[dt.datetime | None] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "kind IN ('fission','fusion','hire','retrain','close')",
            name="ck_org_change_kind",
        ),
        sa.CheckConstraint(
            "state IN ('draft','locked','approved','rejected','applied',"
            "'measured','withdrawn')",
            name="ck_org_change_state",
        ),
        sa.CheckConstraint(
            "predicted_direction IN ('up','down')",
            name="ck_org_change_direction",
        ),
        sa.CheckConstraint(
            "CAST(predicted_magnitude AS REAL) > 0",
            name="ck_org_change_predicts_something",
        ),
        sa.CheckConstraint(
            "subject_agent <> proposed_by",
            name="ck_org_change_is_not_self_dealing",
        ),
        sa.CheckConstraint(
            "state NOT IN ('applied','measured') OR meeting_ref IS NOT NULL",
            name="ck_org_change_applied_was_decided_in_a_room",
        ),
    )


class OrgMetricSnapshot(Base):
    """One org metric, for one subject, at one moment.

    Kept as rows rather than recomputed on demand because the before/after
    comparison an ``OrgChange`` rests on has to survive the company changing
    underneath it. A backlog depth recomputed six weeks later is a different
    number about a different company.
    """

    __tablename__ = "org_metric_snapshots"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(sa.String(64), index=True)
    """An agent ref, a charter id, or ``AURELIS`` for the whole company."""

    metric: Mapped[str] = mapped_column(sa.String(48), index=True)
    value: Mapped[str | None] = mapped_column(sa.String(24))
    """NULL where the record could not support the measurement. Not zero — a
    coverage area with no outputs and one that was never measurable are
    different facts, and only one of them is a reason to split a role."""

    detail: Mapped[str] = mapped_column(sa.Text, default="")
    change_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    taken_at: Mapped[dt.datetime] = mapped_column(index=True)


class CoverageTransfer(Base):
    """Every charter that has ever changed hands.

    The audit trail for the growth mechanism. Coverage is never deleted and
    recreated — it **moves**, by a single UPDATE — so this table plus the
    current holder reconstructs the whole history of who was answerable for
    what, at any past moment.
    """

    __tablename__ = "coverage_transfers"

    transfer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    charter_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    from_agent: Mapped[str] = mapped_column(sa.String(24), index=True)
    to_agent: Mapped[str] = mapped_column(sa.String(24), index=True)
    change_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    reason: Mapped[str] = mapped_column(sa.Text, default="")
    transferred_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "from_agent <> to_agent", name="ck_transfer_actually_moves"
        ),
    )


class OrgExperiment(Base):
    """Two org shapes, the same twelve worlds, and what the count said.

    This is ``CLAUDE.md`` §16 as arithmetic. "Does adding an adversarial
    researcher reduce false discoveries?" and "do three analysts beat two?" are
    settled by running the training suite over both panels and counting, not by
    anyone's judgement about team composition.

    ``verdict`` is recorded whichever way it comes out, and the most useful
    results so far are the ones where the answer was **no difference**.
    """

    __tablename__ = "org_experiments"

    experiment_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    question: Mapped[str] = mapped_column(sa.Text)
    control_name: Mapped[str] = mapped_column(sa.String(48))
    treatment_name: Mapped[str] = mapped_column(sa.String(48))
    control_panel: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    treatment_panel: Mapped[list[str]] = mapped_column(sa.JSON, default=list)

    catalogue_digest: Mapped[str] = mapped_column(sa.String(64), index=True)
    replications: Mapped[int] = mapped_column(default=0)

    control_caught: Mapped[int] = mapped_column(default=0)
    control_missed: Mapped[int] = mapped_column(default=0)
    control_false_alarms: Mapped[int] = mapped_column(default=0)
    treatment_caught: Mapped[int] = mapped_column(default=0)
    treatment_missed: Mapped[int] = mapped_column(default=0)
    treatment_false_alarms: Mapped[int] = mapped_column(default=0)

    verdict: Mapped[str] = mapped_column(sa.String(24), index=True)
    """``treatment_better`` | ``control_better`` | ``no_difference`` |
    ``mixed``."""

    detail: Mapped[str] = mapped_column(sa.Text, default="")
    ran_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "verdict IN ('treatment_better','control_better','no_difference','mixed')",
            name="ck_org_experiment_verdict",
        ),
    )
