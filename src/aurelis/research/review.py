"""The Research Review: a confirmed claim, challenged and killed.

This is M5's target demonstration, and it is the most convincing thing the
project can show early because nobody intervenes at any point.

.. code-block:: text

    a researcher registers a claim and runs it   -> CONFIRMED
    a Critic reads the specification             -> alleges SURVIVORSHIP
    the Chair dispatches the mechanical test     -> point-in-time re-run
    the measurement comes back worse             -> objection UPHELD
    the decision is blocked                      -> hypothesis REFUTED

The original result is real: on a universe of names that are still trading, the
rotation rule genuinely keeps drawdown low. It is also worthless, because that
universe was chosen knowing which names survived — and the rule is drawn to
exactly the names that did not, since those looked best right up until they
went to nothing.

What settles it is a number, not an argument. The Critic does not compose the
test; it names a defect, and :mod:`aurelis.meetings.taxonomy` builds the varied
specification. Everything the room sees is a measurement with an artifact
behind it.

On the numbers
--------------

martex-quant's own corpus found this defect on real crypto history, where it
took a headline Sharpe of 1.47 down to 0.86. Those figures belong to that
corpus and are **not** reproduced here — Aurelis has no market data of its own
yet. What is reproduced is the *mechanism*, on fixture instruments where the
bias is present by construction and therefore measurable. The figures below are
whatever the engine computes; nothing is asserted in advance.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from aurelis.engines.spec import (
    DataSpec,
    ExperimentSpec,
    SignalSpec,
    UniverseSpec,
)
from aurelis.meetings.chair import Chair, ProposedObjection
from aurelis.meetings.taxonomy import MARKET_DEFECTS, build_test
from aurelis.meetings.types import MeetingType, ObjectionStatus, ObjectionType
from aurelis.research.lifecycle import Research
from aurelis.research.states import HypothesisState, RegistrationKind, Verdict
from aurelis.research.tables import Hypothesis

__all__ = ["ReviewOutcome", "hold_research_review", "survivorship_claim"]


def survivorship_claim(bars: int = 200) -> ExperimentSpec:
    """The specification under review: a rotation rule on a survivor universe.

    ``point_in_time=False`` is the defect, and it is stated in the spec rather
    than hidden in a data pipeline — which is the only reason a Critic can see
    it and a test can vary it.
    """
    return ExperimentSpec(
        engine="local",
        universe=UniverseSpec(
            desk="crypto",
            symbols=(),
            point_in_time=False,
            selection="survivors_only",
        ),
        data=DataSpec(source="fixture", bars=bars),
        signal=SignalSpec(kind="rotation", lookback=12, parameters={"top_k": 1}),
        metrics=("total_return", "sharpe", "max_drawdown", "n_trades", "cost_drag"),
    )


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    """What the review established, and how."""

    hypothesis_ref: str
    meeting_ref: str
    objection_ref: str
    objection_status: ObjectionStatus
    verdict_before: Verdict
    verdict_after: Verdict
    claimed: Decimal
    measured: Decimal
    metric: str
    universe_before: int
    universe_after: int
    excluded: tuple[str, ...]
    detail: str

    @property
    def overturned(self) -> bool:
        """Whether the review changed the company's mind."""
        return (
            self.verdict_before is Verdict.CONFIRMED
            and self.verdict_after is not Verdict.CONFIRMED
        )

    def describe(self) -> str:
        return (
            f"{self.metric} {self.claimed} -> {self.measured} once "
            f"{len(self.excluded)} delisted name(s) are restored; "
            f"{self.verdict_before.value} -> {self.verdict_after.value}"
        )


def hold_research_review(
    session: Session,
    *,
    research: Research,
    chair: Chair,
    author: str,
    critic: str,
    chair_ref: str,
    participants: tuple[str, ...],
    registrar: str,
    bars: int = 200,
    at: dt.datetime | None = None,
) -> ReviewOutcome:
    """Run the whole demonstration. No human decides anything.

    The claim is deliberately one the biased run *passes*: a review that only
    ever killed things that were already failing would demonstrate nothing.
    """
    spec = survivorship_claim(bars)
    metric = "max_drawdown"
    claimed_bound = Decimal("0.20")

    # What this design can actually resolve. The block bootstrap puts a
    # roughly 20-percentage-point interval around a 200-bar maximum drawdown,
    # because a drawdown is a property of one path and resampling moves it a
    # long way. A registration claiming to resolve five points would be
    # UNDERPOWERED and the verdict rule would say so -- correctly. Declaring
    # what the data can support, before looking at it, is the discipline
    # rather than a concession to it.
    minimum_effect = Decimal("0.11")

    # 1. The claim, registered before anything runs.
    hypothesis = research.propose(
        session,
        claim=(
            "A top-1 rotation over the crypto desk keeps maximum drawdown "
            "below 20%."
        ),
        author=author,
        minimum_effect=minimum_effect,
        primary_metric=metric,
        family="strategy.rotation.crypto",
        desk="crypto",
        rationale="Fixture instruments; the universe is the survivors list.",
        at=at,
    )
    research.screen(session, hypothesis.ref, at=at)
    registration = research.register(
        session,
        hypothesis_ref=hypothesis.ref,
        spec=spec,
        registrar=registrar,
        declared_cells=4,
        analysis_plan="Peak-to-trough drawdown over the whole window.",
        pass_criteria=[
            {"metric": metric, "comparison": "lt", "value": str(claimed_bound), "on": "point"}
        ],
        kind=RegistrationKind.CONFIRMATORY,
        at=at,
    )
    experiment = research.design(
        session, registration_ref=registration.ref, designer=author, at=at
    )
    run, artifact = research.execute(session, experiment_ref=experiment.ref, at=at)
    first = research.conclude(
        session,
        run_ref=run.ref,
        artifact=artifact,
        author=author,
        interpretation="Drawdown stayed inside the registered bound.",
        at=at,
    )

    claimed = artifact.metrics.get(metric).value
    universe_before = len(artifact.diagnostics["universe"])

    # 2. The Critic names a defect. It does not compose the test.
    defect = MARKET_DEFECTS[ObjectionType.SURVIVORSHIP]
    test = build_test(
        ObjectionType.SURVIVORSHIP, spec, metric=metric, observed=claimed
    )

    meeting = chair.convene(
        session,
        meeting_type=MeetingType.RESEARCH_REVIEW,
        subject=f"Review of {hypothesis.ref}: {hypothesis.claim}",
        chair=chair_ref,
        participants=participants,
        subject_ref=hypothesis.ref,
        trigger="a confirmatory result was registered and must be challenged",
        desk="crypto",
        evidence={
            "claim": hypothesis.claim,
            "verdict_so_far": first.verdict.value,
            "measured": {m.name: str(m.value) for m in artifact.metrics.metrics},
            "universe_basis": artifact.diagnostics["universe_basis"],
            "universe": artifact.diagnostics["universe"],
            "registration": registration.ref,
            "spec_digest": registration.spec_digest[:16],
        },
        at=at,
    )
    chair.run(
        session,
        meeting.ref,
        objections=(
            ProposedObjection(
                author=critic,
                type=ObjectionType.SURVIVORSHIP,
                severity=defect.severity,
                target=hypothesis.ref,
                statement=(
                    "The universe is the list of instruments still trading, so "
                    "the rule was ranking names already known to have survived. "
                    "A top-1 rotation is drawn to whatever is running hottest, "
                    "and the names that later delisted ran hottest of all right "
                    "before they stopped. Re-run point-in-time and the drawdown "
                    "will breach the registered bound."
                ),
                test=test,
            ),
        ),
        at=at,
    )

    # 3. What the test actually returned.
    from aurelis.meetings.tables import MeetingObjection

    objection = (
        session.query(MeetingObjection)
        .filter(MeetingObjection.meeting_ref == meeting.ref)
        .one()
    )
    status = ObjectionStatus(objection.status)
    measured = Decimal(str(objection.test_result.get("observed") or "0"))

    # 4. If the objection held, the claim is refuted -- by the measurement.
    verdict_after = first.verdict
    if status is ObjectionStatus.UPHELD:
        _refute(
            session,
            research,
            hypothesis.ref,
            reason=(
                f"{defect.name} upheld in {meeting.ref}: {metric} measured "
                f"{measured} point-in-time against a registered bound of "
                f"{claimed_bound}. The confirmed result depended on a universe "
                "chosen knowing which names survived."
            ),
            at=at,
        )
        verdict_after = Verdict.REFUTED

    pit_artifact_universe = int(objection.test_result.get("universe_size", 0) or 0)
    excluded = tuple(artifact.diagnostics.get("excluded_by_hindsight", ()))

    return ReviewOutcome(
        hypothesis_ref=hypothesis.ref,
        meeting_ref=meeting.ref,
        objection_ref=objection.ref,
        objection_status=status,
        verdict_before=first.verdict,
        verdict_after=verdict_after,
        claimed=claimed,
        measured=measured,
        metric=metric,
        universe_before=universe_before,
        universe_after=pit_artifact_universe or universe_before,
        excluded=excluded,
        detail=str(objection.test_result.get("detail", "")),
    )


def _refute(
    session: Session,
    research: Research,
    hypothesis_ref: str,
    *,
    reason: str,
    at: dt.datetime | None = None,
) -> Hypothesis:
    """Move a confirmed hypothesis to refuted, on the strength of a test.

    Reached only when a critical objection was **upheld by a measurement**.
    The path exists because a corpus that could not overturn its own
    conclusions would be a corpus that had stopped doing research.
    """
    hypothesis = research.hypothesis(session, hypothesis_ref)
    hypothesis.verdict_reason = reason
    hypothesis.state = HypothesisState.REFUTED
    hypothesis.settled_at = at or research._clock.now()  # noqa: SLF001
    session.flush()

    from aurelis.core.enums import EventKind

    research._ledger.append(  # noqa: SLF001
        session,
        kind=EventKind.VERDICT_OVERTURNED,
        subject=hypothesis_ref,
        payload={"from": "confirmed", "to": "refuted", "reason": reason[:400]},
        at=at,
    )
    return hypothesis
