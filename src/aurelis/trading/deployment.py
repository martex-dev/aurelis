"""Putting an authored version into a paper book, or saying why it cannot go.

The company had no operator path from "an agent designed this" to "the book
holds it", and building one turned out to be almost entirely about the
refusals. There are three places a deployment stops, and each of them is a
different kind of *no*:

**The strategy has not been through research.** ``PROMISING`` is a claim, and
the only evidence for it here is the verdict its own preregistration returned.
A deployment that walked a strategy up the state machine regardless would be
writing that claim itself.

**A gate has no observable.** :mod:`aurelis.trading.readiness` reads seven
gates out of the record and reports silence where the record holds nothing.
A silent gate is left unevaluated, and
:meth:`~aurelis.strategy.lifecycle.Strategies.promote` refuses on exactly that
— which is the behaviour it already had, now reachable from a command.

**A gate answers and fails.** The ordinary case, and the one worth having: a
number, a criterion fixed before the number existed, and a comparison.

Everything this module writes is a criterion, an evaluation, a state change or
an allocation. It computes no metric of its own.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.errors import IntegrityViolation
from aurelis.portfolio.tables import Allocation
from aurelis.research.states import Verdict
from aurelis.strategy.gates import default_criteria
from aurelis.strategy.states import Gate, PortfolioMode, StrategyState
from aurelis.strategy.tables import PromotionGate, StrategyVersion
from aurelis.trading.readiness import Readiness, gather, intended_notional, unmet

__all__ = ["Deployment", "RESEARCH_WALK", "deploy"]

RESEARCH_WALK: tuple[tuple[StrategyState, str], ...] = (
    (StrategyState.CANDIDATE, "an agent authored it from the closed design space"),
    (StrategyState.RESEARCHING, "its design was locked and run against the criteria"),
    (StrategyState.PROMISING, "the registration it locked came back confirmed"),
    (StrategyState.UNDER_REVIEW, "presented to the gates with its measured evidence"),
)
"""The states a deployment walks, and the reason each one is true.

Written here rather than passed in, because a reason supplied by a caller is a
reason nobody checked. ``PROMISING`` is conditional on the verdict and
:func:`deploy` refuses to assert it otherwise — the other three follow from
facts already on the record.
"""


@dataclass(frozen=True, slots=True)
class Deployment:
    """What a deployment attempt did, whether or not it deployed."""

    version_ref: str
    portfolio_ref: str
    weight: Decimal
    readiness: Readiness
    deployed: bool = False
    already: bool = False
    """Whether it was in the book before this command ran.

    Kept apart from ``deployed`` because "we put it there" and "it was already
    there" are different facts, and a command that reported the second as the
    first would let a re-run look like a decision.
    """

    refusal: str = ""
    registered: tuple[str, ...] = ()
    evaluated: tuple[str, ...] = ()
    failures: tuple[str, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        if self.already:
            return (
                f"{self.version_ref} is already allocated in "
                f"{self.portfolio_ref}; nothing was changed"
            )
        if self.deployed:
            return (
                f"{self.version_ref} deployed to {self.portfolio_ref} at "
                f"weight {self.weight}"
            )
        return f"{self.version_ref} was not deployed: {self.refusal}"


def _version(session: Session, version_ref: str) -> StrategyVersion:
    version = session.execute(
        sa.select(StrategyVersion).where(StrategyVersion.ref == version_ref)
    ).scalar_one_or_none()
    if version is None:
        raise IntegrityViolation(f"no strategy version {version_ref}")
    return version


def _verdict(session: Session, version_ref: str) -> str:
    from aurelis.authoring.tables import AuthoringAttempt

    verdict = session.execute(
        sa.select(AuthoringAttempt.verdict).where(
            AuthoringAttempt.version_ref == version_ref
        )
    ).scalar_one_or_none()
    if verdict is None:
        raise IntegrityViolation(
            f"{version_ref} has no recorded authoring attempt, so whether its "
            "own claim was confirmed is unknown"
        )
    return str(verdict)


def deploy(
    runtime: Any,
    session: Session,
    *,
    version_ref: str,
    portfolio_ref: str,
    weight: Decimal,
    actors: dict[str, str],
    meeting_ref: str = "MTG-0002",
    at: dt.datetime | None = None,
) -> Deployment:
    """Take one authored version as far towards a paper book as it can go.

    Writes the gate criteria first and the evaluations second, in that order,
    because a criterion chosen after its observation is a description of what
    happened. Both are ordinary records with a registrar and a timestamp, and
    the trigger behind them refuses an evaluation that predates its criterion.
    """
    moment = at or runtime.clock.now()
    version = _version(session, version_ref)
    intended = intended_notional(
        session, portfolio_ref=portfolio_ref, weight=weight
    )
    readiness = gather(
        session,
        version_ref=version_ref,
        portfolio_ref=portfolio_ref,
        intended=intended,
    )
    failures = unmet(readiness, version.desk)

    live = session.execute(
        sa.select(Allocation.ref).where(
            Allocation.portfolio_ref == portfolio_ref,
            Allocation.version_ref == version_ref,
            Allocation.withdrawn_at.is_(None),
        )
    ).scalars().first()
    if live is not None:
        # Deploying twice would walk the strategy back down its own state
        # machine, which the machine refuses -- correctly, and with a
        # traceback at whoever typed the command twice. Answered here instead.
        return Deployment(
            version_ref,
            portfolio_ref,
            weight,
            readiness,
            deployed=True,
            already=True,
            failures=failures,
        )

    verdict = _verdict(session, version_ref)
    if verdict != Verdict.CONFIRMED.value:
        return Deployment(
            version_ref,
            portfolio_ref,
            weight,
            readiness,
            refusal=(
                f"its registration came back {verdict}, not confirmed. "
                "PROMISING is a claim about evidence, and the only evidence "
                "for this version is the verdict it earned"
            ),
            failures=failures,
        )

    for target, reason in RESEARCH_WALK:
        runtime.strategies.transition(
            session,
            strategy_ref=version.strategy_ref,
            target=target,
            reason=reason,
            actor=actors["validator"],
            at=moment,
        )

    criteria = default_criteria(version.desk)
    already = {
        str(gate)
        for gate in session.execute(
            sa.select(PromotionGate.gate).where(
                PromotionGate.version_ref == version_ref
            )
        ).scalars()
    }
    registered: list[str] = []
    for gate in Gate:
        # Skipped rather than re-registered, and asked rather than caught: a
        # second registration raises on purpose, because re-registering after
        # a disappointing measurement is how a threshold becomes a
        # description. A broad except here would have swallowed that refusal
        # along with an unknown comparison.
        if gate.value in already:
            continue
        criterion = criteria[gate]
        runtime.gates.register(
            session,
            version_ref=version_ref,
            gate=gate,
            metric=str(criterion["metric"]),
            comparison=str(criterion["comparison"]),
            value=Decimal(str(criterion["value"])),
            registered_by=actors["validator"],
            note=str(criterion.get("note", "")),
            at=moment,
        )
        registered.append(gate.value)

    evaluated: list[str] = []
    for item in readiness.answerable:
        if item.value is None:  # pragma: no cover - answerable excludes None
            continue
        runtime.gates.evaluate(
            session,
            version_ref=version_ref,
            gate=item.gate,
            observed=item.value,
            evaluated_by=actors["validator"],
            at=moment,
        )
        evaluated.append(item.gate.value)

    promoted = runtime.strategies.promote(
        session,
        version_ref=version_ref,
        decided_by_meeting=meeting_ref,
        actor=actors["governor"],
        at=moment,
    )
    if not isinstance(promoted, StrategyVersion):
        return Deployment(
            version_ref,
            portfolio_ref,
            weight,
            readiness,
            refusal=promoted.reason,
            registered=tuple(registered),
            evaluated=tuple(evaluated),
            failures=failures,
        )

    runtime.strategies.transition(
        session,
        strategy_ref=version.strategy_ref,
        target=StrategyState.PAPER_TRADING,
        reason="every gate evaluated and passed; Risk holds the sleeve limit",
        actor=actors["risk"],
        at=moment,
    )

    # Risk sets the ceiling before the first intent exists. An assessment
    # against no limit at all allows whatever was asked for, which is Risk
    # agreeing with the strategy rather than bounding it.
    runtime.risk.set_limit(
        session,
        scope="version",
        scope_id=version_ref,
        metric="exposure",
        bound=intended,
        reason=(
            f"{version_ref} is allocated {weight} of {portfolio_ref}; no single "
            "intent may exceed the sleeve the Board actually granted it"
        ),
        set_by=actors["risk"],
        at=moment,
    )
    runtime.book.allocate(
        session,
        portfolio_ref=portfolio_ref,
        version_ref=version_ref,
        weight=weight,
        rationale=(
            f"gates A-G evaluated from the record and passed; deployed at "
            f"{weight} for a forward paper walk"
        ),
        decided_by=actors["portfolio"],
        at=moment,
    )
    return Deployment(
        version_ref,
        portfolio_ref,
        weight,
        readiness,
        deployed=True,
        registered=tuple(registered),
        evaluated=tuple(evaluated),
        failures=failures,
    )


def open_paper_book(
    runtime: Any,
    session: Session,
    *,
    desk: str,
    equity: Decimal,
    opened_by: str,
    at: dt.datetime | None = None,
) -> str:
    """The desk's paper book, opened once and reused.

    ``PortfolioMode.PAPER`` is not a flag on a live book — it is the only mode
    a book opened here can have, and there is no adapter behind any other.
    """
    from aurelis.portfolio.tables import Portfolio

    existing = session.execute(
        sa.select(Portfolio.ref)
        .where(Portfolio.mode == PortfolioMode.PAPER.value)
        .order_by(Portfolio.created_at)
    ).scalars().first()
    if existing is not None:
        return str(existing)
    book = runtime.book.open(
        session,
        name=f"{desk} paper book",
        desks=(desk,),
        mode=PortfolioMode.PAPER,
        initial_equity=equity,
        opened_by=opened_by,
        at=at,
    )
    return str(book.ref)
