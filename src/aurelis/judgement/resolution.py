"""Settling a thesis against a recording, once.

The resolver is deliberately stupid. It does not fetch, it does not interpret,
and it does not decide. For every sealed thesis whose horizon has passed, it
looks for a recording of the instrument that covers the horizon, reads the
close of the bar that opened at the horizon, compares it to the reference
close, and writes the outcome and the Brier score. If no recording covers the
horizon it says so and leaves the row open — a thesis is never resolved by
guessing, and never by a bar that has not been recorded.

The one rule of consequence: **strictly above.** A close equal to the
reference is not above it, so ``up`` loses a tie and ``down`` wins one. Ties
are rare at eight decimal places and the rule is stated so that nobody has to
wonder which way the resolver leans.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock, isoformat
from aurelis.core.enums import Actor, EventKind
from aurelis.intel.snapshots import MarketSnapshot, SnapshotBar
from aurelis.judgement.tables import Thesis
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["Resolution", "due", "resolve_due"]


@dataclass(frozen=True, slots=True)
class Resolution:
    """What happened to one due thesis."""

    ref: str
    agent_ref: str
    instrument: str
    scored: bool
    detail: str
    outcome: bool | None = None
    brier: Decimal | None = None
    hit: bool | None = None

    def describe(self) -> str:
        if not self.scored:
            return f"{self.ref} {self.instrument}: pending — {self.detail}"
        return (
            f"{self.ref} {self.instrument}: {'right' if self.hit else 'wrong'}, "
            f"Brier {self.brier} — {self.detail}"
        )


def due(session: Session, *, at: dt.datetime) -> list[Thesis]:
    """Sealed theses whose horizon has passed and which have not been scored."""
    return list(
        session.execute(
            sa.select(Thesis)
            .where(Thesis.scored_at.is_(None), Thesis.resolves_at <= at)
            .order_by(Thesis.resolves_at, Thesis.ref)
        ).scalars()
    )


def _covering(session: Session, thesis: Thesis) -> MarketSnapshot | None:
    """The newest recording of the instrument that reaches the horizon.

    A recording must *extend past* the horizon, not merely contain a bar before
    it: the last bar of a recording made before the horizon would settle the
    proposition with a price from the wrong time.
    """
    return (
        session.execute(
            sa.select(MarketSnapshot)
            .where(
                MarketSnapshot.symbol == thesis.instrument,
                MarketSnapshot.interval == thesis.interval,
                MarketSnapshot.is_live == thesis.is_live,
                MarketSnapshot.last_at >= thesis.resolves_at,
                MarketSnapshot.first_at <= thesis.resolves_at,
            )
            .order_by(MarketSnapshot.fetched_at.desc(), MarketSnapshot.ref.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def resolve_due(
    session: Session,
    *,
    ledger: Ledger | None = None,
    clock: Clock | None = None,
    at: dt.datetime | None = None,
) -> list[Resolution]:
    """Score every due thesis a recording can settle; report the rest as pending."""
    the_clock = clock or SystemClock()
    the_ledger = ledger or Ledger(the_clock)
    moment = at or the_clock.now()
    out: list[Resolution] = []

    for thesis in due(session, at=moment):
        snapshot = _covering(session, thesis)
        if snapshot is None:
            out.append(
                Resolution(
                    thesis.ref,
                    thesis.agent_ref,
                    thesis.instrument,
                    scored=False,
                    detail=(
                        f"no recording of {thesis.instrument} covers "
                        f"{isoformat(thesis.resolves_at)}; one has to be fetched"
                    ),
                )
            )
            continue

        bar = session.execute(
            sa.select(SnapshotBar.timestamp, SnapshotBar.close)
            .where(
                SnapshotBar.snapshot_ref == snapshot.ref,
                SnapshotBar.timestamp <= thesis.resolves_at,
            )
            .order_by(SnapshotBar.timestamp.desc())
            .limit(1)
        ).first()
        if bar is None:  # pragma: no cover - excluded by first_at <= resolves_at
            continue
        when, close_text = bar
        when = when if when.tzinfo else when.replace(tzinfo=dt.UTC)
        close = Decimal(str(close_text))
        reference = Decimal(thesis.reference_close)
        outcome = close > reference
        realised = Decimal(1) if outcome else Decimal(0)
        brier = ((thesis.probability_up - realised) ** 2).quantize(Decimal("0.0001"))
        hit = outcome == (thesis.direction == "up")

        thesis.outcome = outcome
        thesis.resolution_at = when
        thesis.resolution_close = str(close)
        thesis.brier = brier
        thesis.scored_at = moment
        thesis.scored_against = snapshot.ref
        session.flush()

        detail = (
            f"close {close} at {isoformat(when)} against reference {reference}, "
            f"read from {snapshot.ref}"
        )
        the_ledger.append(
            session,
            kind=EventKind.THESIS_SCORED,
            actor=Actor.SYSTEM,
            subject=thesis.ref,
            payload={
                "agent": thesis.agent_ref,
                "instrument": thesis.instrument,
                "direction": thesis.direction,
                "confidence": str(thesis.confidence),
                "outcome_up": outcome,
                "hit": hit,
                "brier": str(brier),
                "resolution_close": str(close),
                "resolution_at": isoformat(when),
                "against": snapshot.ref,
            },
            at=moment,
        )
        out.append(
            Resolution(
                thesis.ref,
                thesis.agent_ref,
                thesis.instrument,
                scored=True,
                detail=detail,
                outcome=outcome,
                brier=brier,
                hit=hit,
            )
        )
    return out
