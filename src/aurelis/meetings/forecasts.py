"""Scoring forecasts, and reading calibration off them.

This is the mechanism ADR-0005 leans on hardest, because it is the only
per-agent quality signal that costs almost nothing and is not circular. No
model grades another model's prose; a probability recorded before an outcome is
compared with the outcome.

The Brier score is ``(p - outcome)^2``. Lower is better. The reference point
worth remembering: **0.25 is what you get by always saying 50%**. An agent
whose Brier score sits at 0.25 is not calibrated, it is abstaining in numeric
form, and the report says so rather than colouring it green.

A forecast is scored exactly once, against a named outcome. Rescoring would let
a bad prediction be quietly improved when more became known.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.meetings.tables import Forecast
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["Calibration", "ForecastScorer", "UNINFORMATIVE_BRIER"]

UNINFORMATIVE_BRIER = Decimal("0.25")
"""What always saying 50% scores. The bar a forecaster must beat to be
saying anything at all."""


@dataclass(frozen=True, slots=True)
class Calibration:
    """One agent's forecasting record."""

    agent_ref: str
    scored: int
    mean_brier: Decimal | None

    @property
    def informative(self) -> bool:
        """Whether this agent is doing better than always guessing 50%."""
        return self.mean_brier is not None and self.mean_brier < UNINFORMATIVE_BRIER

    def describe(self) -> str:
        if self.mean_brier is None:
            return f"{self.agent_ref}: no scored forecasts yet"
        verdict = "informative" if self.informative else "no better than 50/50"
        return (
            f"{self.agent_ref}: Brier {self.mean_brier} over {self.scored} "
            f"forecast(s) — {verdict}"
        )


class ForecastScorer:
    """Resolves forecasts against outcomes and reports calibration."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def score(
        self,
        session: Session,
        *,
        meeting_ref: str,
        outcome: bool,
        against: str,
        at: dt.datetime | None = None,
    ) -> list[Forecast]:
        """Score every unscored forecast from one meeting.

        ``against`` names what settled it — the retrospective, the run, the
        decision. A score without a stated resolver is a number nobody can
        check.
        """
        moment = at or self._clock.now()
        rows = session.execute(
            sa.select(Forecast).where(
                Forecast.meeting_ref == meeting_ref, Forecast.scored_at.is_(None)
            )
        ).scalars().all()

        realised = Decimal(1) if outcome else Decimal(0)
        for forecast in rows:
            forecast.outcome = outcome
            forecast.brier = (forecast.probability - realised) ** 2
            forecast.scored_at = moment
            forecast.scored_against = against
        session.flush()

        if rows:
            self._ledger.append(
                session,
                kind=EventKind.FORECAST_SCORED,
                subject=meeting_ref,
                payload={
                    "scored": len(rows),
                    "outcome": outcome,
                    "against": against,
                    "mean_brier": str(
                        sum((f.brier or Decimal(0) for f in rows), Decimal(0))
                        / Decimal(len(rows))
                    ),
                },
                at=moment,
            )
        return list(rows)

    def rescore_is_refused(self, session: Session, meeting_ref: str) -> None:
        """Guard: a forecast is scored once, against one outcome."""
        already = session.execute(
            sa.select(sa.func.count())
            .select_from(Forecast)
            .where(Forecast.meeting_ref == meeting_ref, Forecast.scored_at.is_not(None))
        ).scalar_one()
        if already:
            raise IntegrityViolation(
                f"{meeting_ref} already has {already} scored forecast(s); "
                "rescoring would let a bad prediction be quietly improved once "
                "more became known"
            )

    def calibration(self, session: Session, agent_ref: str) -> Calibration:
        scored, total = session.execute(
            sa.select(
                sa.func.count(),
                sa.func.coalesce(sa.func.sum(sa.cast(Forecast.brier, sa.Numeric(12, 8))), 0),
            ).where(Forecast.agent_ref == agent_ref, Forecast.scored_at.is_not(None))
        ).one()
        count = int(scored)
        if not count:
            return Calibration(agent_ref, 0, None)
        mean = (Decimal(str(total)) / Decimal(count)).quantize(Decimal("0.0001"))
        return Calibration(agent_ref, count, mean)

    def company_calibration(self, session: Session) -> list[Calibration]:
        refs = session.execute(
            sa.select(Forecast.agent_ref)
            .where(Forecast.scored_at.is_not(None))
            .group_by(Forecast.agent_ref)
            .order_by(Forecast.agent_ref)
        ).scalars().all()
        return [self.calibration(session, ref) for ref in refs]
