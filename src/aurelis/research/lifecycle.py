"""The research lifecycle, from a claim to a verdict.

.. code-block:: text

    propose   -> DRAFT       a researcher states a claim and a minimum effect
    screen    -> SCREENED    prior art checked; duplicates shelved unspent
    register  -> REGISTERED  the Registrar locks and hashes the spec
    design    -> DESIGNED    the experiment is built from the locked spec
    execute   -> ANALYZED    an engine runs; results are written by machine
    conclude  -> verdict     derived from the registered criteria, by rule

Every number comes from an engine and carries the digest of the data it was
computed from. Every verdict comes from a pure function that sees only what was
registered beforehand. The researcher's contribution is the claim, the design
and the interpretation — never the measurement and never the verdict.

The order is enforced by the database, not by this class. What lives here is
the bookkeeping; what makes it honest is in :mod:`aurelis.research.triggers`.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.engines.protocol import RunArtifact
from aurelis.engines.registry import engine_for
from aurelis.engines.spec import ExperimentSpec
from aurelis.platform.artifacts.store import ArtifactStore
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger
from aurelis.research.states import (
    ComputedBy,
    EvidenceKind,
    HypothesisState,
    Polarity,
    RegistrationKind,
    RunStatus,
    Verdict,
    may_transition,
)
from aurelis.research.tables import (
    Evidence,
    Experiment,
    Finding,
    Hypothesis,
    Registration,
    Result,
    Run,
)
from aurelis.research.verdict import VerdictReport, derive_verdict, parse_criteria

__all__ = ["Research", "ResearchOutcome"]


@dataclass(frozen=True, slots=True)
class ResearchOutcome:
    """A settled hypothesis and the trail behind it."""

    hypothesis_ref: str
    registration_ref: str
    experiment_ref: str
    run_ref: str
    finding_ref: str
    verdict: Verdict
    report: VerdictReport
    artifact_digest: str
    metrics: dict[str, str]

    def describe(self) -> str:
        return f"{self.hypothesis_ref}: {self.verdict.value} — {self.report.reason}"


class Research:
    """Runs the lifecycle. Owns no judgement of its own."""

    __slots__ = ("_artifacts", "_clock", "_ledger")

    def __init__(
        self,
        artifacts: ArtifactStore,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    # ------------------------------------------------------------- propose

    def propose(
        self,
        session: Session,
        *,
        claim: str,
        author: str,
        minimum_effect: Decimal,
        primary_metric: str,
        family: str,
        rationale: str = "",
        desk: str | None = None,
        project_ref: str | None = None,
        parent_ref: str | None = None,
        derivation: str = "root",
        at: dt.datetime | None = None,
    ) -> Hypothesis:
        """State a claim, with the smallest effect that would matter.

        ``minimum_effect`` is required. Without it an interval too wide to
        answer the question is indistinguishable from one that answered it,
        and UNDERPOWERED becomes undetectable.
        """
        if minimum_effect <= 0:
            raise IntegrityViolation(
                "minimum_effect must be positive: it is the smallest effect "
                "worth caring about, and a zero one makes every result "
                "significant"
            )
        moment = at or self._clock.now()
        ref = allocate_ref(session, RefKind.HYPOTHESIS)
        session.add(
            Hypothesis(
                hypothesis_id=uuid7(),
                ref=ref,
                claim=claim,
                rationale=rationale,
                minimum_effect=minimum_effect,
                primary_metric=primary_metric,
                family=family,
                author=author,
                desk=desk,
                project_ref=project_ref,
                parent_ref=parent_ref,
                derivation=derivation,
                state=HypothesisState.DRAFT,
                created_at=moment,
            )
        )
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.HYPOTHESIS_PROPOSED,
            actor=author,
            subject=ref,
            payload={
                "claim": claim[:200],
                "family": family,
                "minimum_effect": str(minimum_effect),
                "primary_metric": primary_metric,
                "derivation": derivation,
            },
            at=moment,
        )
        return self.hypothesis(session, ref)

    def screen(
        self,
        session: Session,
        hypothesis_ref: str,
        *,
        prior_art: tuple[str, ...] = (),
        shelve: bool = False,
        reason: str = "",
        at: dt.datetime | None = None,
    ) -> Hypothesis:
        """Check for prior art before spending anything.

        "Have we tried this before?" is one of the most valuable questions the
        company can ask, and it is cheapest to ask here. A duplicate is shelved
        before it consumes a registration slot or a token of budget.
        """
        moment = at or self._clock.now()
        hypothesis = self.hypothesis(session, hypothesis_ref)
        hypothesis.prior_art = list(prior_art)
        target = HypothesisState.SHELVED if shelve else HypothesisState.SCREENED
        self._move(session, hypothesis, target, reason=reason, at=moment)
        return hypothesis

    # ------------------------------------------------------------ register

    def register(
        self,
        session: Session,
        *,
        hypothesis_ref: str,
        spec: ExperimentSpec,
        pass_criteria: list[dict[str, Any]],
        registrar: str,
        analysis_plan: str = "",
        kind: RegistrationKind = RegistrationKind.CONFIRMATORY,
        declared_cells: int = 1,
        supersedes: str | None = None,
        at: dt.datetime | None = None,
    ) -> Registration:
        """Lock and hash a preregistration.

        Criteria are parsed here, before locking, so a registration whose
        criteria could not be evaluated is refused rather than sitting locked
        and unevaluable. ``declared_cells`` is what the family declared, not
        what it will run — that is the number the deflated Sharpe deflates
        against.
        """
        moment = at or self._clock.now()
        hypothesis = self.hypothesis(session, hypothesis_ref)
        parse_criteria(pass_criteria)  # refuses malformed criteria before locking

        if supersedes is not None:
            kind = RegistrationKind.EXPLORATORY

        ref = allocate_ref(session, RefKind.REGISTRATION)
        payload = {
            "hypothesis": hypothesis_ref,
            "kind": kind.value,
            "spec": spec.as_payload(),
            "spec_digest": spec.digest(),
            "pass_criteria": pass_criteria,
            "analysis_plan": analysis_plan,
            "seed": spec.seed,
            "declared_cells": declared_cells,
        }
        stored = self._artifacts.put_json(
            session, payload, kind="registration", produced_by=ref
        )

        session.add(
            Registration(
                registration_id=uuid7(),
                ref=ref,
                hypothesis_ref=hypothesis_ref,
                kind=kind.value,
                spec=spec.as_payload(),
                spec_digest=spec.digest(),
                analysis_plan=analysis_plan,
                pass_criteria=pass_criteria,
                seed=spec.seed,
                declared_cells=declared_cells,
                family=hypothesis.family,
                locked_at=moment,
                locked_by=registrar,
                supersedes=supersedes,
                degraded_reason=(
                    "revised after an earlier registration; degraded to exploratory "
                    "so it cannot be reported as confirmation"
                    if supersedes
                    else ""
                ),
                artifact_digest=stored.digest,
                created_at=moment,
            )
        )
        session.flush()
        if hypothesis.state == HypothesisState.SCREENED:
            self._move(session, hypothesis, HypothesisState.REGISTERED, at=moment)
        # A superseding registration deliberately does not rewind the
        # hypothesis. The revision is a new bet on the same claim, recorded
        # alongside the original; moving the state backwards would erase the
        # fact that the first design had already been designed and possibly run.

        self._ledger.append(
            session,
            kind=EventKind.REGISTRATION_LOCKED,
            actor=registrar,
            subject=ref,
            payload={
                "hypothesis": hypothesis_ref,
                "kind": kind.value,
                "spec_digest": spec.digest()[:16],
                "declared_cells": declared_cells,
                "criteria": len(pass_criteria),
                "artifact": stored.digest[:12],
            },
            at=moment,
        )
        return self.registration(session, ref)

    def design(
        self,
        session: Session,
        *,
        registration_ref: str,
        designer: str,
        at: dt.datetime | None = None,
    ) -> Experiment:
        """Build the experiment from the locked spec, and nothing else.

        The spec comes out of the registration, not from the caller. An
        experiment built from anything other than what was locked would make
        the lock decorative.
        """
        moment = at or self._clock.now()
        registration = self.registration(session, registration_ref)
        if registration.locked_at is None:
            raise IntegrityViolation(
                f"{registration_ref} is not locked; nothing may be designed from "
                "a registration that could still change"
            )

        ref = allocate_ref(session, RefKind.EXPERIMENT)
        session.add(
            Experiment(
                experiment_id=uuid7(),
                ref=ref,
                registration_ref=registration_ref,
                hypothesis_ref=registration.hypothesis_ref,
                engine=str(registration.spec.get("engine", "local")),
                spec=registration.spec,
                spec_digest=registration.spec_digest,
                designed_by=designer,
                created_at=moment,
            )
        )
        session.flush()
        self._move(
            session,
            self.hypothesis(session, registration.hypothesis_ref),
            HypothesisState.DESIGNED,
            at=moment,
        )
        return session.execute(
            sa.select(Experiment).where(Experiment.ref == ref)
        ).scalar_one()

    # --------------------------------------------------------------- run

    def execute(
        self,
        session: Session,
        *,
        experiment_ref: str,
        at: dt.datetime | None = None,
    ) -> tuple[Run, RunArtifact]:
        """Run the experiment. The engine produces every number.

        A completed run's results are written with ``computed_by=engine``,
        which the table's CHECK constraint is the only accepted value for
        besides the Custodian. There is no path by which an agent's opinion
        becomes a measurement.
        """
        moment = at or self._clock.now()
        experiment = self.experiment(session, experiment_ref)
        registration = self.registration(session, experiment.registration_ref)
        spec = _spec_from_payload(experiment.spec)

        hypothesis = self.hypothesis(session, experiment.hypothesis_ref)
        if hypothesis.state == HypothesisState.DESIGNED:
            self._move(session, hypothesis, HypothesisState.RUNNING, at=moment)

        ref = allocate_ref(session, RefKind.RUN)
        started = time.perf_counter()
        try:
            engine = engine_for(spec)
            artifact = engine.run(spec)
        except Exception as error:
            # A scientific failure is a research object, not a retry. Recorded
            # with its reason, and the hypothesis does not silently continue.
            session.add(
                Run(
                    run_id=uuid7(),
                    ref=ref,
                    experiment_ref=experiment_ref,
                    registration_ref=registration.ref,
                    engine=experiment.engine,
                    code_version="",
                    data_fingerprint="",
                    seed=registration.seed,
                    status=RunStatus.SCIENTIFIC_FAILURE,
                    failure_reason=f"{type(error).__name__}: {error}",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    started_at=moment,
                )
            )
            session.flush()
            self._ledger.append(
                session,
                kind=EventKind.RUN_FAILED,
                subject=ref,
                payload={"experiment": experiment_ref, "reason": str(error)[:300]},
                at=moment,
            )
            raise

        stored = self._artifacts.put_json(
            session, artifact.as_payload(), kind="run", produced_by=ref
        )
        session.add(
            Run(
                run_id=uuid7(),
                ref=ref,
                experiment_ref=experiment_ref,
                registration_ref=registration.ref,
                engine=experiment.engine,
                code_version=artifact.code_version,
                data_fingerprint=artifact.data_fingerprint,
                seed=artifact.seed,
                status=RunStatus.COMPLETED,
                artifact_digest=stored.digest,
                duration_ms=int((time.perf_counter() - started) * 1000),
                started_at=moment,
            )
        )
        session.flush()

        for metric in artifact.metrics.metrics:
            session.add(
                Result(
                    result_id=uuid7(),
                    run_ref=ref,
                    metric=metric.name,
                    value=metric.value,
                    low=metric.low,
                    high=metric.high,
                    unit=metric.unit,
                    method=metric.method,
                    split="train",
                    computed_by=ComputedBy.ENGINE,
                    artifact_digest=stored.digest,
                    created_at=moment,
                )
            )
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.RUN_COMPLETED,
            subject=ref,
            payload={
                "experiment": experiment_ref,
                "engine": experiment.engine,
                "spec_digest": artifact.spec_digest[:16],
                "data_fingerprint": artifact.data_fingerprint[:16],
                "artifact": stored.digest[:12],
                "metrics": len(artifact.metrics.metrics),
            },
            at=moment,
        )
        self._move(
            session,
            self.hypothesis(session, experiment.hypothesis_ref),
            HypothesisState.ANALYZED,
            at=moment,
        )
        return session.execute(sa.select(Run).where(Run.ref == ref)).scalar_one(), artifact

    # ---------------------------------------------------------- conclude

    def conclude(
        self,
        session: Session,
        *,
        run_ref: str,
        artifact: RunArtifact,
        author: str,
        interpretation: str,
        at: dt.datetime | None = None,
    ) -> ResearchOutcome:
        """Derive the verdict and record the finding.

        The verdict is computed from the registered criteria and the measured
        interval. ``interpretation`` is the researcher's words about it, and it
        cannot change what the verdict is.
        """
        moment = at or self._clock.now()
        run = self.run(session, run_ref)
        registration = self.registration(session, run.registration_ref)
        hypothesis = self.hypothesis(session, registration.hypothesis_ref)

        report = derive_verdict(
            artifact.metrics,
            parse_criteria(registration.pass_criteria),
            minimum_effect=hypothesis.minimum_effect,
            primary_metric=hypothesis.primary_metric,
        )

        finding_ref = allocate_ref(session, RefKind.FINDING)
        stored = self._artifacts.put_json(
            session,
            {
                "hypothesis": hypothesis.ref,
                "run": run_ref,
                "verdict": report.verdict.value,
                "reason": report.reason,
                "checks": list(report.checks),
                "interpretation": interpretation,
                "metrics": artifact.metrics.as_payload(),
            },
            kind="finding",
            produced_by=finding_ref,
        )
        session.add(
            Finding(
                finding_id=uuid7(),
                ref=finding_ref,
                hypothesis_ref=hypothesis.ref,
                run_ref=run_ref,
                statement=interpretation,
                verdict=report.verdict.value,
                verdict_reason=report.reason,
                verdict_checks=list(report.checks),
                author=author,
                confidence_cap_reason=(
                    "exploratory registration: this cannot be reported as confirmation"
                    if registration.kind == RegistrationKind.EXPLORATORY
                    else ""
                ),
                artifact_digest=stored.digest,
                created_at=moment,
            )
        )
        session.flush()

        # The measurement itself, at the only level that names an artifact.
        session.add(
            Evidence(
                evidence_id=uuid7(),
                finding_ref=finding_ref,
                kind=EvidenceKind.OBSERVED_FACT,
                polarity=(
                    Polarity.SUPPORTS
                    if report.verdict is Verdict.CONFIRMED
                    else Polarity.CONTRADICTS
                ),
                statement=(
                    f"{hypothesis.primary_metric} measured by {run.engine} "
                    f"at code {run.code_version}"
                ),
                artifact_digest=run.artifact_digest,
                author=author,
                created_at=moment,
            )
        )
        session.flush()

        terminal = {
            Verdict.CONFIRMED: HypothesisState.CONFIRMED,
            Verdict.REFUTED: HypothesisState.REFUTED,
            Verdict.INCONCLUSIVE: HypothesisState.INCONCLUSIVE,
            Verdict.UNDERPOWERED: HypothesisState.UNDERPOWERED,
        }.get(report.verdict)
        if terminal is not None:
            hypothesis.verdict_reason = report.reason
            hypothesis.settled_at = moment
            self._move(session, hypothesis, terminal, at=moment)

        self._ledger.append(
            session,
            kind=EventKind.VERDICT_DERIVED,
            actor=author,
            subject=hypothesis.ref,
            payload={
                "verdict": report.verdict.value,
                "reason": report.reason[:300],
                "run": run_ref,
                "finding": finding_ref,
                "checks": list(report.checks),
            },
            at=moment,
        )
        return ResearchOutcome(
            hypothesis_ref=hypothesis.ref,
            registration_ref=registration.ref,
            experiment_ref=run.experiment_ref,
            run_ref=run_ref,
            finding_ref=finding_ref,
            verdict=report.verdict,
            report=report,
            artifact_digest=stored.digest,
            metrics={m.name: str(m.value) for m in artifact.metrics.metrics},
        )

    # -------------------------------------------------------------- reading

    def hypothesis(self, session: Session, ref: str) -> Hypothesis:
        row = session.execute(
            sa.select(Hypothesis).where(Hypothesis.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no hypothesis {ref!r}")
        return row

    def registration(self, session: Session, ref: str) -> Registration:
        row = session.execute(
            sa.select(Registration).where(Registration.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no registration {ref!r}")
        return row

    def experiment(self, session: Session, ref: str) -> Experiment:
        row = session.execute(
            sa.select(Experiment).where(Experiment.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no experiment {ref!r}")
        return row

    def run(self, session: Session, ref: str) -> Run:
        row = session.execute(sa.select(Run).where(Run.ref == ref)).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no run {ref!r}")
        return row

    def trial_count(self, session: Session, family: str | None = None) -> int:
        """Every registration ever locked, counted by declared cells.

        The multiple-testing denominator. A family path prefix owns its
        subtree, and the count is of what was *declared*, so a grid that
        declared two hundred cells costs two hundred whether or not it ran
        them all. This is the number that makes the graveyard load-bearing.
        """
        query = sa.select(
            sa.func.coalesce(sa.func.sum(Registration.declared_cells), 0)
        ).where(Registration.locked_at.is_not(None))
        if family is not None:
            query = query.where(
                sa.or_(
                    Registration.family == family,
                    Registration.family.startswith(f"{family}."),
                )
            )
        return int(session.execute(query).scalar_one())

    def graveyard(self, session: Session, limit: int = 50) -> list[Hypothesis]:
        """Everything the company killed, and why. A first-class query."""
        return list(
            session.execute(
                sa.select(Hypothesis)
                .where(
                    Hypothesis.state.in_(
                        [
                            HypothesisState.REFUTED,
                            HypothesisState.INCONCLUSIVE,
                            HypothesisState.UNDERPOWERED,
                            HypothesisState.SHELVED,
                        ]
                    )
                )
                .order_by(Hypothesis.settled_at.desc().nullslast(), Hypothesis.ref)
                .limit(limit)
            )
            .scalars()
            .all()
        )

    # -------------------------------------------------------------- helpers

    def _move(
        self,
        session: Session,
        hypothesis: Hypothesis,
        target: HypothesisState,
        *,
        reason: str = "",
        at: dt.datetime | None = None,
    ) -> None:
        if not may_transition(hypothesis.state, target.value):
            raise IntegrityViolation(
                f"{hypothesis.ref} cannot go {hypothesis.state} -> {target.value}"
            )
        previous, hypothesis.state = hypothesis.state, target.value
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.HYPOTHESIS_STATE_CHANGED,
            actor=Actor.SYSTEM,
            subject=hypothesis.ref,
            payload={"from": previous, "to": target.value, "reason": reason},
            at=at or self._clock.now(),
        )


def _spec_from_payload(payload: dict[str, Any]) -> ExperimentSpec:
    """Rebuild a spec from what was locked.

    Reconstructed from the stored payload rather than carried in memory, so
    what runs is provably what was registered.
    """
    from decimal import Decimal as D

    from aurelis.engines.spec import (
        BacktestSpec,
        CostModel,
        DataSpec,
        SignalSpec,
        UniverseSpec,
    )

    universe = payload["universe"]
    data = payload["data"]
    signal = payload["signal"]
    backtest = payload["backtest"]
    costs = backtest["costs"]
    return ExperimentSpec(
        engine=str(payload["engine"]),
        universe=UniverseSpec(
            desk=str(universe["desk"]),
            symbols=tuple(universe["symbols"]),
            point_in_time=bool(universe["point_in_time"]),
            selection=str(universe["selection"]),
        ),
        data=DataSpec(
            source=str(data["source"]),
            bars=int(data["bars"]),
            interval=str(data["interval"]),
            start=data.get("start"),
            end=data.get("end"),
        ),
        signal=SignalSpec(
            kind=str(signal["kind"]),
            lookback=int(signal["lookback"]),
            threshold=D(str(signal["threshold"])),
            parameters=dict(signal.get("parameters") or {}),
        ),
        backtest=BacktestSpec(
            initial_cash=D(str(backtest["initial_cash"])),
            allow_short=bool(backtest["allow_short"]),
            costs=CostModel(
                fee_bps=D(str(costs["fee_bps"])),
                spread_bps=D(str(costs["spread_bps"])),
                slippage_bps=D(str(costs["slippage_bps"])),
            ),
            warmup_bars=int(backtest["warmup_bars"]),
        ),
        seed=int(payload["seed"]),
        metrics=tuple(payload["metrics"]),
    )
