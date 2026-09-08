"""Re-testing a result with a deliberate, declared variation.

The second of the two conditions the mandate reported as **blocked**. The
`replications` table has existed since M5 with a docstring explaining exactly
what it is for, and nothing has ever written a row into it — the record shape
was built and the act it records was not.

A replication is not a re-run. Running the identical specification again
returns the identical number, because every engine here is deterministic, and
learning that determinism holds is not evidence about a market. So a
replication **must vary something**, the variation must be named from a closed
set, and the result is judged by the *same* criteria the original was locked
to.

Why it spends no error budget
-----------------------------

M5's own note on the table says it: a replication "is not a new bet on the same
data". A grid that tries two hundred cells and reports the best is a false
discovery machine, and `declared_cells` exists so a search pays for its width.
A replication is the opposite move — it is asking whether one already-declared
result *survives* a perturbation, and every outcome is reported. Charging it to
the denominator would penalise checking your own work.

That reasoning only holds because the variation is declared **before** the
replication runs and the criteria are inherited rather than chosen. A
"replication" free to pick its own bar afterwards would be a second bet wearing
the word.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.engines.registry import engine_for
from aurelis.engines.spec import ExperimentSpec, spec_from_payload
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger
from aurelis.research.tables import Hypothesis, Registration, Replication
from aurelis.research.verdict import derive_verdict, parse_criteria

__all__ = [
    "ReplicationOutcome",
    "ReplicationReport",
    "Replications",
    "Variation",
    "replications_of",
    "vary",
]


class Variation(StrEnum):
    """What a replication is allowed to change. A closed set.

    Free-form variation would make "we replicated it" unfalsifiable: nobody
    could say afterwards whether the thing that changed was supposed to matter.
    Each of these is a different question about the same result.
    """

    SEED = "seed"
    """The same rule, the same window, a different random draw. Answers: was
    the result an artefact of one resampling?"""

    EARLIER_WINDOW = "earlier_window"
    """The same rule on the bars *before* the ones it was fitted on. The
    strongest of the three, and the only one that shows the rule anything it
    has not already seen."""

    SHORTER_WINDOW = "shorter_window"
    """The same rule on the most recent two thirds. Answers: does it depend on
    the oldest part of the sample?"""


class ReplicationOutcome(StrEnum):
    HELD = "held"
    """The verdict came back the same. The value counted by
    :mod:`aurelis.memory.confidence`, spelled the way that module already reads
    it -- a second spelling here would have silently counted zero forever."""

    BROKE = "broke"
    """The verdict changed. The most valuable outcome in the table: a result
    that does not survive a declared variation was never one result."""

    UNDERPOWERED = "underpowered"
    """The variation left too little data to say either way. Not a failure of
    the original and not a pass -- reported as itself."""

    NOTHING_TO_REPLICATE = "nothing_to_replicate"
    """The original never settled, so there was no result to hold.

    Found on the very first run of this module: three variations of an
    underpowered registration all came back underpowered, the verdicts matched,
    and every one was recorded as ``held``. Same verdict is not the same as a
    result surviving -- and :mod:`aurelis.memory.confidence` counts ``held``
    rows as evidence, so replications of nothing would have accumulated into
    confidence about nothing.
    """


@dataclass(frozen=True, slots=True)
class ReplicationReport:
    """What one replication established."""

    ref: str
    parent_registration_ref: str
    variation: Variation
    outcome: ReplicationOutcome
    original_verdict: str
    replicated_verdict: str
    detail: str

    @property
    def held(self) -> bool:
        return self.outcome is ReplicationOutcome.HELD

    @property
    def settled_anything(self) -> bool:
        """Whether there was a result here at all to hold or break."""
        return self.outcome in (
            ReplicationOutcome.HELD,
            ReplicationOutcome.BROKE,
        )

    def describe(self) -> str:
        return (
            f"{self.ref}: {self.variation.value} -> {self.outcome.value} "
            f"({self.original_verdict} vs {self.replicated_verdict})"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "registration": self.parent_registration_ref,
            "variation": self.variation.value,
            "outcome": self.outcome.value,
            "original_verdict": self.original_verdict,
            "replicated_verdict": self.replicated_verdict,
            "detail": self.detail,
        }


def vary(spec: ExperimentSpec, variation: Variation) -> ExperimentSpec:
    """The varied specification. A pure function of the original and the choice.

    Deliberately pure and deliberately small: a reader must be able to see that
    the variation changed one thing, and only that. It never touches the
    signal, the costs or the universe basis — a replication that changed the
    rule would be testing a different rule.
    """
    from dataclasses import replace

    if variation is Variation.SEED:
        # A different draw, same everything else. +1 rather than random: a
        # replication nobody can repeat is not a replication.
        return replace(spec, seed=spec.seed + 1)
    if variation is Variation.SHORTER_WINDOW:
        shorter = max(spec.signal.lookback * 3, (spec.data.bars * 2) // 3)
        if shorter >= spec.data.bars:
            raise IntegrityViolation(
                f"a shorter window of {shorter} is not shorter than "
                f"{spec.data.bars}; this specification is already at the "
                "minimum the signal can run on"
            )
        return replace(spec, data=replace(spec.data, bars=shorter))
    # EARLIER_WINDOW: the bars before the original ones. The fixture and
    # snapshot sources both serve the most recent `bars`, so asking for twice
    # as many and skipping the recent half is how "earlier" is expressed
    # without a second source protocol.
    return replace(
        spec,
        data=replace(spec.data, bars=spec.data.bars * 2),
        backtest=replace(spec.backtest, warmup_bars=spec.data.bars),
    )


class Replications:
    """Running a declared variation, and writing down what happened."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def replicate(
        self,
        session: Session,
        *,
        registration_ref: str,
        variation: Variation,
        author: str,
        at: dt.datetime | None = None,
    ) -> ReplicationReport:
        """Re-test a locked registration under one declared variation.

        The criteria are **inherited**, never re-chosen. A replication free to
        pick its own bar afterwards would be a second bet wearing the word, and
        the reason it costs no error budget would stop holding.
        """
        moment = at or self._clock.now()
        registration = session.execute(
            sa.select(Registration).where(Registration.ref == registration_ref)
        ).scalar_one_or_none()
        if registration is None:
            raise IntegrityViolation(f"no registration {registration_ref}")
        if registration.locked_at is None:
            raise IntegrityViolation(
                f"{registration_ref} was never locked. Replicating an unlocked "
                "registration would inherit criteria that could still change."
            )

        original = spec_from_payload(registration.spec)
        varied = vary(original, variation)
        if varied.digest() == original.digest():
            raise IntegrityViolation(
                f"the {variation.value} variation left the specification "
                "identical. A replication that varied nothing is a re-run, and "
                "every engine here is deterministic."
            )

        hypothesis = session.execute(
            sa.select(Hypothesis).where(
                Hypothesis.ref == registration.hypothesis_ref
            )
        ).scalar_one()
        criteria = parse_criteria(registration.pass_criteria)
        # Inherited whole: the criteria, the minimum effect and the primary
        # metric all come from what was locked. A replication that re-chose any
        # of the three would be a second bet wearing the word.
        before = derive_verdict(
            _metrics(original),
            criteria,
            minimum_effect=hypothesis.minimum_effect,
            primary_metric=hypothesis.primary_metric,
        )
        after = derive_verdict(
            _metrics(varied),
            criteria,
            minimum_effect=hypothesis.minimum_effect,
            primary_metric=hypothesis.primary_metric,
        )

        outcome = _judge(before.verdict.value, after.verdict.value)
        ref = allocate_ref(session, RefKind.REPLICATION)
        detail = (
            f"{variation.value}: {before.verdict.value} -> {after.verdict.value}. "
            f"{after.reason}"
        )

        session.add(
            Replication(
                replication_id=uuid7(),
                ref=ref,
                parent_registration_ref=registration_ref,
                run_ref=None,
                varied=(
                    f"{variation.value}; spec digest "
                    f"{original.digest()[:12]} -> {varied.digest()[:12]}"
                ),
                outcome=outcome.value,
                detail=detail,
                author=author,
                created_at=moment,
            )
        )
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.REPLICATION_RECORDED,
            actor=author,
            subject=ref,
            payload={
                "registration": registration_ref,
                "variation": variation.value,
                "outcome": outcome.value,
                "original_verdict": before.verdict.value,
                "replicated_verdict": after.verdict.value,
                "spec_digest": varied.digest()[:16],
                "spends_error_budget": False,
            },
            at=moment,
        )

        return ReplicationReport(
            ref=ref,
            parent_registration_ref=registration_ref,
            variation=variation,
            outcome=outcome,
            original_verdict=before.verdict.value,
            replicated_verdict=after.verdict.value,
            detail=detail,
        )


def _metrics(spec: ExperimentSpec) -> Any:
    """Run a specification and hand back what it measured."""
    return engine_for(spec).run(spec).metrics


_UNSETTLED = frozenset({"underpowered", "inconclusive"})


def _judge(before: str, after: str) -> ReplicationOutcome:
    """What one variation established, in the order the questions matter.

    **Whether the original settled is asked first.** A registration that came
    back underpowered has no result to replicate, and a variation of it that is
    also underpowered agrees about nothing. The first version of this checked
    only whether the verdicts matched, so three replications of an unsettled
    claim were all recorded as ``held`` -- which
    :mod:`aurelis.memory.confidence` counts as evidence.

    Then power: a variation that shortened the window until nothing could be
    concluded says something about the variation rather than about the result,
    and calling it a break would make every ``SHORTER_WINDOW`` replication look
    like a refutation.
    """
    if before in _UNSETTLED:
        return ReplicationOutcome.NOTHING_TO_REPLICATE
    if after in _UNSETTLED:
        return ReplicationOutcome.UNDERPOWERED
    if before == after:
        return ReplicationOutcome.HELD
    return ReplicationOutcome.BROKE


def replications_of(session: Session, registration_ref: str) -> list[Replication]:
    return list(
        session.execute(
            sa.select(Replication)
            .where(Replication.parent_registration_ref == registration_ref)
            .order_by(Replication.created_at)
        ).scalars()
    )
