"""Portfolio construction: what the book would like to hold.

Separate from signal generation, per `CLAUDE.md` §11, and separate from Risk.
Three layers with three different answers, and all three persisted, so a reader
can see where a number was cut.

The load-bearing piece here is :meth:`Portfolio.correlation` and the gate C
evaluation it feeds. The best individual strategy is not automatically a
portfolio component: a version can pass every solo test and still add nothing
to a book it moves with. Gate C is where that is caught, and it is caught with
a *measured* correlation over the versions actually allocated — not an
assumption, and not a number anybody typed.

Correlation is computed with Decimal arithmetic over returns the engines
produced. Slow and exact, which is the right trade for a figure that decides
whether capital is deployed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.chain import payload_hash
from aurelis.platform.ledger.ledger import Ledger
from aurelis.portfolio.tables import Allocation, ExposureSnapshot, Portfolio
from aurelis.strategy.states import PortfolioMode

__all__ = ["Book", "Correlations", "Exposure", "correlation"]

getcontext().prec = 28


@dataclass(frozen=True, slots=True)
class Correlations:
    """A measured correlation matrix over allocated versions."""

    members: tuple[str, ...]
    values: dict[tuple[str, str], Decimal]
    observations: int

    def between(self, left: str, right: str) -> Decimal | None:
        if left == right:
            return Decimal("1")
        return self.values.get((left, right)) or self.values.get((right, left))

    def max_against(self, version_ref: str) -> tuple[str, Decimal] | None:
        """The strongest correlation between this version and any member.

        What gate C compares against. Returns ``None`` when the book is empty —
        which is a real state and must not be read as "uncorrelated": the first
        strategy into an empty book has nothing to be independent *of*.
        """
        best: tuple[str, Decimal] | None = None
        for other in self.members:
            if other == version_ref:
                continue
            value = self.between(version_ref, other)
            if value is None:
                continue
            if best is None or abs(value) > abs(best[1]):
                best = (other, value)
        return best

    def as_payload(self) -> dict[str, str]:
        return {f"{a}|{b}": str(v) for (a, b), v in sorted(self.values.items())}


def correlation(left: list[Decimal], right: list[Decimal]) -> Decimal | None:
    """Pearson correlation, in exact decimal arithmetic.

    Returns ``None`` rather than zero when it is undefined — fewer than two
    observations, or a series with no variance. A flat series is not
    uncorrelated with anything; the question simply has no answer, and
    answering it with 0 would let a constant strategy pass an independence
    gate.
    """
    n = min(len(left), len(right))
    if n < 2:
        return None
    xs, ys = left[:n], right[:n]

    mean_x = sum(xs, Decimal(0)) / n
    mean_y = sum(ys, Decimal(0)) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]

    numerator = sum((a * b for a, b in zip(dx, dy, strict=True)), Decimal(0))
    var_x = sum((a * a for a in dx), Decimal(0))
    var_y = sum((b * b for b in dy), Decimal(0))
    if var_x <= 0 or var_y <= 0:
        return None

    denominator = (var_x * var_y).sqrt()
    if denominator == 0:  # pragma: no cover - guarded above
        return None
    return (numerator / denominator).quantize(Decimal("0.00000001"))


@dataclass(frozen=True, slots=True)
class Exposure:
    """A snapshot of the book."""

    gross: Decimal
    net: Decimal
    by_desk: dict[str, Decimal]
    concentration: Decimal
    members: tuple[str, ...]

    def describe(self) -> str:
        return (
            f"gross {self.gross}, net {self.net}, "
            f"largest single weight {self.concentration}, "
            f"{len(self.members)} allocated"
        )


class Book:
    """Opens portfolios, allocates to versions, measures what results."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def open(
        self,
        session: Session,
        *,
        name: str,
        desks: tuple[str, ...],
        mode: PortfolioMode,
        initial_equity: Decimal,
        opened_by: str,
        constraints: dict[str, Any] | None = None,
        at: dt.datetime | None = None,
    ) -> Portfolio:
        """Open a book in one of the three permitted modes."""
        moment = at or self._clock.now()
        ref = allocate_ref(session, RefKind.PORTFOLIO)
        portfolio = Portfolio(
            portfolio_id=uuid7(),
            ref=ref,
            name=name,
            desks=list(desks),
            mode=mode.value,
            initial_equity=initial_equity,
            constraints=dict(constraints or {}),
            opened_by=opened_by,
            created_at=moment,
        )
        session.add(portfolio)
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.PORTFOLIO_OPENED,
            actor=opened_by,
            subject=ref,
            payload={
                "name": name,
                "mode": mode.value,
                "desks": list(desks),
                "initial_equity": str(initial_equity),
            },
            at=moment,
        )
        return portfolio

    def allocate(
        self,
        session: Session,
        *,
        portfolio_ref: str,
        version_ref: str,
        weight: Decimal,
        rationale: str,
        decided_by: str,
        capacity: Decimal | None = None,
        meeting_ref: str | None = None,
        at: dt.datetime | None = None,
    ) -> Allocation:
        """Give a version a share of the book.

        Refuses to over-allocate. A book whose weights sum past one is claiming
        leverage nobody decided on, and the arithmetic that produced it would
        be invisible in every downstream number.
        """
        if not rationale.strip():
            raise IntegrityViolation(
                "an allocation must say why; a weight with no stated reason is "
                "a number somebody typed into a portfolio"
            )
        moment = at or self._clock.now()
        live = self.allocations(session, portfolio_ref)
        total = sum((row.weight for row in live), Decimal(0)) + weight
        if total > 1:
            raise IntegrityViolation(
                f"allocating {weight} to {version_ref} would take the book to "
                f"{total}. A book above 1.0 is claiming leverage nobody decided"
            )

        ref = allocate_ref(session, RefKind.ALLOCATION)
        allocation = Allocation(
            allocation_id=uuid7(),
            ref=ref,
            portfolio_ref=portfolio_ref,
            version_ref=version_ref,
            weight=weight,
            capacity=capacity,
            rationale=rationale,
            decided_by_meeting=meeting_ref,
            decided_by=decided_by,
            decided_at=moment,
        )
        session.add(allocation)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.ALLOCATION_DECIDED,
            actor=decided_by,
            subject=portfolio_ref,
            payload={
                "allocation": ref,
                "version": version_ref,
                "weight": str(weight),
                "book_total": str(total),
                "meeting": meeting_ref,
            },
            at=moment,
        )
        return allocation

    def allocations(self, session: Session, portfolio_ref: str) -> list[Allocation]:
        """Live allocations — withdrawn ones stay on the record, out of the sum."""
        return list(
            session.execute(
                sa.select(Allocation)
                .where(
                    Allocation.portfolio_ref == portfolio_ref,
                    Allocation.withdrawn_at.is_(None),
                )
                .order_by(Allocation.decided_at)
            ).scalars()
        )

    def exposure(self, session: Session, portfolio_ref: str) -> Exposure:
        rows = self.allocations(session, portfolio_ref)
        by_desk: dict[str, Decimal] = {}
        for row in rows:
            desk = self._desk_of(session, row.version_ref)
            by_desk[desk] = by_desk.get(desk, Decimal(0)) + row.weight

        gross = sum((row.weight for row in rows), Decimal(0))
        largest = max((row.weight for row in rows), default=Decimal(0))
        return Exposure(
            gross=gross,
            net=gross,
            by_desk=by_desk,
            concentration=largest,
            members=tuple(row.version_ref for row in rows),
        )

    def correlations(
        self,
        session: Session,
        portfolio_ref: str,
        *,
        returns: dict[str, list[Decimal]],
        candidate: str | None = None,
    ) -> Correlations:
        """Measure correlation across the allocated versions, plus a candidate.

        ``returns`` comes from the engines. This module does not compute
        returns and must not: a portfolio layer that produced its own
        performance numbers would be a second source of truth about how a
        strategy behaved.
        """
        members = list(self.exposure(session, portfolio_ref).members)
        if candidate and candidate not in members:
            members.append(candidate)

        values: dict[tuple[str, str], Decimal] = {}
        observations = 0
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                series_l, series_r = returns.get(left), returns.get(right)
                if not series_l or not series_r:
                    continue
                observations = max(observations, min(len(series_l), len(series_r)))
                value = correlation(series_l, series_r)
                if value is not None:
                    values[(left, right)] = value
        return Correlations(tuple(members), values, observations)

    def snapshot(
        self,
        session: Session,
        *,
        portfolio_ref: str,
        correlations: Correlations,
        at: dt.datetime | None = None,
    ) -> ExposureSnapshot:
        """Persist what the book was, so a gate can cite it later."""
        moment = at or self._clock.now()
        exposure = self.exposure(session, portfolio_ref)
        matrix = correlations.as_payload()

        snapshot = ExposureSnapshot(
            snapshot_id=uuid7(),
            portfolio_ref=portfolio_ref,
            gross=exposure.gross,
            net=exposure.net,
            by_desk={desk: str(weight) for desk, weight in exposure.by_desk.items()},
            concentration=exposure.concentration,
            correlation=matrix,
            correlation_digest=payload_hash(matrix),
            members=list(exposure.members),
            taken_at=moment,
        )
        session.add(snapshot)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.EXPOSURE_SNAPSHOT,
            actor="system",
            subject=portfolio_ref,
            payload={
                "gross": str(exposure.gross),
                "concentration": str(exposure.concentration),
                "members": len(exposure.members),
                "correlation_digest": snapshot.correlation_digest[:16],
            },
            at=moment,
        )
        return snapshot

    @staticmethod
    def _desk_of(session: Session, version_ref: str) -> str:
        from aurelis.strategy.tables import StrategyVersion

        desk = session.execute(
            sa.select(StrategyVersion.desk).where(StrategyVersion.ref == version_ref)
        ).scalar()
        return str(desk or "unknown")
