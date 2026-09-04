"""The research record.

``registrations`` is the most protected table in the system. Three invariants
hold on it and they are all database triggers, because a rule the application
enforces is a rule that any new code path, migration or SQL console can walk
around:

* a ``Run`` cannot exist unless a **locked** registration for its experiment
  predates it;
* once locked, a registration's spec, criteria, seed and kind cannot change —
  a revised design is a *new row*, degraded to exploratory;
* a ``Result`` can only be written by an engine or the Custodian.

``declared_cells`` is what the family **declared**, not what it ran. A grid of
twenty features by ten horizons costs two hundred even if fifty were executed.
That closes the declare-big-run-small loophole in multiple-testing accounting,
and it is the number the deflated Sharpe deflates against.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from aurelis.platform.db.tables import Base
from aurelis.research.states import (
    ComputedBy,
    HypothesisState,
    RegistrationKind,
    RunStatus,
)

__all__ = [
    "Evidence",
    "Experiment",
    "Finding",
    "Hypothesis",
    "Registration",
    "Replication",
    "Result",
    "Run",
]


class Hypothesis(Base):
    """A claim somebody wants to test."""

    __tablename__ = "hypotheses"

    hypothesis_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)

    claim: Mapped[str] = mapped_column(sa.Text)
    rationale: Mapped[str] = mapped_column(sa.Text, default="")

    minimum_effect: Mapped[Decimal] = mapped_column()
    """The smallest effect worth caring about, declared before the run.

    Not decoration: it is what makes UNDERPOWERED detectable. Without it an
    interval too wide to answer the question looks the same as one that
    answered it."""

    primary_metric: Mapped[str] = mapped_column(sa.String(48))
    family: Mapped[str] = mapped_column(sa.String(96), index=True)
    """Hierarchical path, e.g. ``strategy.momentum.crypto``. A path prefix owns
    its subtree for error-budget purposes."""

    author: Mapped[str] = mapped_column(sa.String(24), index=True)
    desk: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    project_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    parent_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)
    derivation: Mapped[str] = mapped_column(sa.String(32), default="root")
    """How this came from its parent: specialisation, generalisation,
    refutation_response, ablation, follow_up_from_failure. Makes "what did we
    learn from the failures?" a query rather than an archaeology project."""

    state: Mapped[str] = mapped_column(
        sa.String(24), default=HypothesisState.DRAFT, index=True
    )
    verdict_reason: Mapped[str] = mapped_column(sa.Text, default="")
    prior_art: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)

    created_at: Mapped[dt.datetime] = mapped_column(index=True)
    settled_at: Mapped[dt.datetime | None] = mapped_column()


class Registration(Base):
    """A preregistration. Locked, hashed, and immutable thereafter."""

    __tablename__ = "registrations"

    registration_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    hypothesis_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    kind: Mapped[str] = mapped_column(sa.String(16), default=RegistrationKind.CONFIRMATORY)
    spec: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    spec_digest: Mapped[str] = mapped_column(sa.String(64), index=True)
    analysis_plan: Mapped[str] = mapped_column(sa.Text, default="")

    pass_criteria: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """Committed BEFORE the run. Evaluated by a pure function that sees
    nothing else."""

    seed: Mapped[int] = mapped_column(default=0)
    declared_cells: Mapped[int] = mapped_column(default=1)
    family: Mapped[str] = mapped_column(sa.String(96), index=True)

    locked_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    locked_by: Mapped[str | None] = mapped_column(sa.String(24))
    """The Registrar, and nobody else. Enforced by write scope."""

    supersedes: Mapped[str | None] = mapped_column(sa.String(24))
    degraded_reason: Mapped[str] = mapped_column(sa.Text, default="")
    artifact_digest: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "kind IN ('confirmatory','exploratory','replication')",
            name="ck_registration_kind",
        ),
        sa.CheckConstraint("declared_cells >= 1", name="ck_declared_cells_positive"),
    )


class Experiment(Base):
    """A registered specification, ready to run."""

    __tablename__ = "experiments"

    experiment_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    registration_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    hypothesis_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    engine: Mapped[str] = mapped_column(sa.String(32), index=True)
    spec: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    spec_digest: Mapped[str] = mapped_column(sa.String(64), index=True)
    designed_by: Mapped[str] = mapped_column(sa.String(24))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)


class Run(Base):
    """One execution. Append-only, and gated on a prior locked registration."""

    __tablename__ = "runs"

    run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    experiment_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    registration_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    """Carried on the row so the trigger can check it without a join through
    a table an attacker could also write."""

    engine: Mapped[str] = mapped_column(sa.String(32))
    code_version: Mapped[str] = mapped_column(sa.String(64))
    data_fingerprint: Mapped[str] = mapped_column(sa.String(64), index=True)
    seed: Mapped[int] = mapped_column()

    status: Mapped[str] = mapped_column(sa.String(24), default=RunStatus.COMPLETED, index=True)
    failure_reason: Mapped[str] = mapped_column(sa.Text, default="")

    artifact_digest: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    duration_ms: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('completed','infra_failure','scientific_failure','timeout','refused')",
            name="ck_run_status",
        ),
    )


class Result(Base):
    """One measured quantity from one run.

    ``computed_by`` accepts only ``engine`` or ``custodian``. That CHECK is
    what makes "no agent writes a number" a property of the database rather
    than a convention of the runtime.
    """

    __tablename__ = "results"

    result_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    metric: Mapped[str] = mapped_column(sa.String(48), index=True)
    value: Mapped[Decimal] = mapped_column()
    low: Mapped[Decimal | None] = mapped_column()
    high: Mapped[Decimal | None] = mapped_column()
    unit: Mapped[str] = mapped_column(sa.String(24), default="")
    method: Mapped[str] = mapped_column(sa.String(128), default="")

    split: Mapped[str] = mapped_column(sa.String(16), default="train", index=True)
    computed_by: Mapped[str] = mapped_column(sa.String(16), default=ComputedBy.ENGINE)
    artifact_digest: Mapped[str] = mapped_column(sa.String(64), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "computed_by IN ('engine','custodian')",
            name="ck_result_computed_by_machine_only",
        ),
        sa.CheckConstraint(
            "split <> 'sealed' OR computed_by = 'custodian'",
            name="ck_sealed_results_come_from_the_custodian",
        ),
        sa.UniqueConstraint("run_ref", "metric", "split", name="uq_one_value_per_metric"),
    )


class Finding(Base):
    """An interpretation of results. Words, never numbers of its own."""

    __tablename__ = "findings"

    finding_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    hypothesis_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    run_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    statement: Mapped[str] = mapped_column(sa.Text)
    verdict: Mapped[str] = mapped_column(sa.String(16), index=True)
    verdict_reason: Mapped[str] = mapped_column(sa.Text)
    verdict_checks: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    """The arithmetic that produced the verdict, kept so a reader can redo it."""

    author: Mapped[str] = mapped_column(sa.String(24), index=True)
    confidence_cap_reason: Mapped[str] = mapped_column(sa.Text, default="")
    artifact_digest: Mapped[str | None] = mapped_column(sa.String(64))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)


class Evidence(Base):
    """One thing supporting or contradicting a finding, at a stated level."""

    __tablename__ = "evidence"

    evidence_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    finding_ref: Mapped[str] = mapped_column(sa.String(24), index=True)

    kind: Mapped[str] = mapped_column(sa.String(24), index=True)
    polarity: Mapped[str] = mapped_column(sa.String(16), default="supports")
    statement: Mapped[str] = mapped_column(sa.Text)

    artifact_digest: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    source: Mapped[str | None] = mapped_column(sa.String(128))
    verbatim: Mapped[str] = mapped_column(sa.Text, default="")
    parent_evidence: Mapped[str | None] = mapped_column(sa.String(24))

    author: Mapped[str] = mapped_column(sa.String(24), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(index=True)

    __table_args__ = (
        sa.CheckConstraint(
            "kind IN ('observed_fact','sourced_claim','inferred_claim',"
            "'hypothesis','speculation')",
            name="ck_evidence_kind",
        ),
        sa.CheckConstraint(
            "kind <> 'observed_fact' OR artifact_digest IS NOT NULL",
            name="ck_observed_fact_names_its_artifact",
        ),
    )


class Replication(Base):
    """A re-test with a deliberate, declared variation.

    Spends no error budget: it is not a new bet on the same data. Surviving one
    is evidence; a stress test that survives confers nothing, which is why the
    two are different records.
    """

    __tablename__ = "replications"

    replication_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(sa.String(24), unique=True, index=True)
    parent_registration_ref: Mapped[str] = mapped_column(sa.String(24), index=True)
    run_ref: Mapped[str | None] = mapped_column(sa.String(24), index=True)

    varied: Mapped[str] = mapped_column(sa.Text)
    """What was deliberately changed. A replication that varied nothing is a
    re-run, and re-running the same thing is not independent evidence."""

    outcome: Mapped[str] = mapped_column(sa.String(24), index=True)
    detail: Mapped[str] = mapped_column(sa.Text, default="")
    author: Mapped[str] = mapped_column(sa.String(24))
    created_at: Mapped[dt.datetime] = mapped_column(index=True)
