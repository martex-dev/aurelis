"""The training record: what the company knows about an agent before it works.

A ``TrainingRun`` is an agent's starting record. It cites the catalogue digest
and the playbook digest, so a score can never be compared against one earned on
different worlds or by a different procedure — which is the failure that would
turn the whole measurement into a number with no referent.

``verdict`` has three values and the third is load-bearing. ``not_scored`` is
what an agent gets when the suite has no fair question for its specialty, and
it is not a pass. Recording it as one would put a certification in the
permanent record of two thirds of the company on no evidence at all.

Rates are stored as **text**, exactly like money, and for the same reason: the
exact decimal survives. That carries the same trap — SQLite compares a number
to a string by type class, so ``'0.5000' >= 0`` is true for any string — and
every CHECK below therefore casts before it compares.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base

__all__ = ["ScenarioMark", "TrainingRun", "TrainingVerdict"]


class TrainingVerdict(StrEnum):
    """What the suite concluded about one agent."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_SCORED = "not_scored"
    """No specialty, or too few settled questions in it to certify anyone.
    Never a pass, never a failure, and always shown as itself."""


class TrainingRun(Base):
    """One agent's pass over the scenario suite."""

    __tablename__ = "training_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    agent_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    playbook_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    playbook_version: Mapped[str] = mapped_column(sa.String(16))
    playbook_digest: Mapped[str] = mapped_column(sa.String(64))
    catalogue_digest: Mapped[str] = mapped_column(sa.String(64), index=True)
    """Which worlds. Two scores from different catalogues are not comparable
    and this is what makes that checkable rather than assumed."""

    replications: Mapped[int] = mapped_column()
    specialty: Mapped[list[str]] = mapped_column(sa.JSON, default=list)

    scenarios: Mapped[int] = mapped_column(default=0)
    caught: Mapped[int] = mapped_column(default=0)
    missed: Mapped[int] = mapped_column(default=0)
    false_alarms: Mapped[int] = mapped_column(default=0)
    true_silences: Mapped[int] = mapped_column(default=0)
    effect_correct: Mapped[int] = mapped_column(default=0)
    effect_wrong: Mapped[int] = mapped_column(default=0)
    effect_unscored: Mapped[int] = mapped_column(default=0)
    unscored_items: Mapped[int] = mapped_column(default=0)

    catch_rate: Mapped[str | None] = mapped_column(sa.String(16))
    false_alarm_rate: Mapped[str | None] = mapped_column(sa.String(16))
    effect_accuracy: Mapped[str | None] = mapped_column(sa.String(16))
    """NULL where the denominator was empty. Not zero: a specialty with no
    planted defects has a catch rate of nothing at all, and zero would fail an
    agent for a gap in the catalogue."""

    verdict: Mapped[str] = mapped_column(sa.String(16), index=True)
    reason: Mapped[str] = mapped_column(sa.Text, default="")
    standard: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    """The bar in force when this was judged, copied in. A standard that later
    rises must not retroactively fail a record that met the old one."""

    measured_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "verdict IN ('passed','failed','not_scored')",
            name="ck_training_run_verdict",
        ),
        sa.CheckConstraint(
            "catch_rate IS NULL OR "
            "(CAST(catch_rate AS REAL) >= 0 AND CAST(catch_rate AS REAL) <= 1)",
            name="ck_training_run_catch_rate_is_a_rate",
        ),
        sa.CheckConstraint(
            "false_alarm_rate IS NULL OR "
            "(CAST(false_alarm_rate AS REAL) >= 0 "
            "AND CAST(false_alarm_rate AS REAL) <= 1)",
            name="ck_training_run_false_alarm_rate_is_a_rate",
        ),
        sa.CheckConstraint(
            "replications > 1",
            name="ck_training_run_replicated",
        ),
    )


class ScenarioMark(Base):
    """One scenario within one training run, graded.

    Kept row by row rather than only in aggregate, because "which question did
    it get wrong?" is the only version of the score that can be acted on.
    """

    __tablename__ = "scenario_marks"

    mark_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_ref: Mapped[str] = mapped_column(
        sa.ForeignKey("training_runs.ref", ondelete="CASCADE"), index=True
    )
    scenario_id: Mapped[str] = mapped_column(sa.String(24), index=True)

    alleged: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    caught: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    missed: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    false_alarms: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    true_silences: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    unscored: Mapped[list[str]] = mapped_column(sa.JSON, default=list)

    effect_call: Mapped[str] = mapped_column(sa.String(16))
    observed: Mapped[str] = mapped_column(sa.String(32))
    """The headline metric on the single draw the critic was shown."""

    __table_args__ = (
        sa.CheckConstraint(
            "effect_call IN ('correct','wrong','unscored')",
            name="ck_scenario_mark_effect_call",
        ),
        sa.UniqueConstraint("run_ref", "scenario_id", name="uq_one_mark_per_scenario"),
    )
