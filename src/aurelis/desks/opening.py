"""Opening a desk: the repeatable sequence, run for real.

The roadmap describes M12 as "a repeatable sequence: register `DeskConfig`,
build or adapt the engine, wire data sources, define the cost and liquidity
model, set risk limits, staff it, run the scenario suite for the desk." This is
that sequence as one method, evaluated rather than asserted.

What opening a desk actually does:

1. run the readiness checklist against the live system,
2. **refuse** if anything failed — a desk with no cost model does not open,
3. write the opening record, carrying every provisional item verbatim,
4. record it in the ledger with the caveats attached.

Step 3 is the one that keeps this honest over time. Every desk opened at M12
runs on fixture data, and the pull towards letting that fade into the
background once the desk works is strong. The caveats live on the row, the
column ``data_is_live`` is false on every desk, and both travel into every
report — so a desk cannot graduate from "open on fixtures" to "open" without
somebody writing down what changed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import uuid7
from aurelis.desks.calendars import calendar_for
from aurelis.desks.costs import costs_for
from aurelis.desks.limits import limits_for
from aurelis.desks.readiness import Assessment, assess
from aurelis.desks.tables import DeskOpening
from aurelis.org.desks import DESKS, Desk, DeskStatus
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["Desks", "OpenedDesk"]


@dataclass(frozen=True, slots=True)
class OpenedDesk:
    """What opening a desk established."""

    desk: Desk
    assessment: Assessment
    calendar: str
    periods_per_year: int
    round_trip_bps: str
    material_size_usd: str
    caveats: tuple[str, ...]

    @property
    def provisional(self) -> bool:
        return bool(self.caveats)

    def describe(self) -> str:
        return (
            f"{self.desk.value}: {self.calendar} "
            f"({self.periods_per_year} bars/yr), "
            f"{self.round_trip_bps}bps round trip, "
            f"${self.material_size_usd} ceiling"
            + (f" — {len(self.caveats)} caveat(s)" if self.caveats else "")
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "desk": self.desk.value,
            "calendar": self.calendar,
            "periods_per_year": self.periods_per_year,
            "round_trip_cost_bps": self.round_trip_bps,
            "material_size_usd": self.material_size_usd,
            "caveats": list(self.caveats),
            "checklist": [i.as_payload() for i in self.assessment.items],
            "data_is_live": False,
        }


class Desks:
    """Opens desks, and refuses to open one that is not ready."""

    __slots__ = ("_ledger", "_clock")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def readiness(self, desk: Desk | str) -> Assessment:
        return assess(desk)

    def open(
        self,
        session: Session,
        desk: Desk | str,
        *,
        opened_by: str = "operator",
        at: dt.datetime | None = None,
    ) -> OpenedDesk:
        """Run the checklist and open the desk, or refuse with the reasons."""
        key = Desk(desk) if isinstance(desk, str) else desk
        moment = at or self._clock.now()
        assessment = assess(key)

        if not assessment.may_open:
            reasons = "; ".join(f"{i.name}: {i.detail}" for i in assessment.failures)
            raise IntegrityViolation(
                f"the {key.value} desk is not ready to open. {reasons}"
            )

        calendar = calendar_for(key.value)
        costs = costs_for(key)
        limits = limits_for(key)
        interval = "1d" if "1d" in calendar.periods else "1h"
        periods = calendar.periods_per_year(interval)

        existing = session.execute(
            sa.select(DeskOpening).where(DeskOpening.desk == key.value)
        ).scalar_one_or_none()
        row = existing or DeskOpening(opening_id=uuid7(), desk=key.value)
        row.status = DeskStatus.ACTIVE.value
        row.calendar = calendar.name
        row.periods_per_year = periods
        row.round_trip_cost_bps = str(costs.round_trip_bps)
        row.material_size_usd = str(costs.liquidity.material_size_usd)
        row.max_gross_leverage = str(limits.max_gross_leverage)
        row.shortable = costs.liquidity.shortable
        row.checklist = [i.as_payload() for i in assessment.items]
        row.caveats = list(assessment.caveats)
        # False on every desk, and a column rather than an inference from the
        # prose above it. "Is anything here real?" should be a query.
        row.data_is_live = False
        row.opened_by = opened_by
        row.opened_at = moment
        if existing is None:
            session.add(row)
        session.flush()

        opened = OpenedDesk(
            desk=key,
            assessment=assessment,
            calendar=calendar.name,
            periods_per_year=periods,
            round_trip_bps=str(costs.round_trip_bps),
            material_size_usd=str(costs.liquidity.material_size_usd),
            caveats=assessment.caveats,
        )
        self._ledger.append(
            session,
            kind=EventKind.DESK_OPENED,
            actor=Actor.OPERATOR if opened_by == "operator" else opened_by,
            subject=key.value,
            payload={
                **opened.as_payload(),
                "cost_basis": costs.basis,
                "limits": limits.as_payload(),
                "caveat": (
                    "Opened on fixture data. Deterministic, offline, and not a "
                    "market. No research conclusion about a real market may be "
                    "drawn from anything this desk produces."
                ),
            },
            at=moment,
        )
        return opened

    def open_all(
        self, session: Session, *, opened_by: str = "operator", at: dt.datetime | None = None
    ) -> tuple[OpenedDesk, ...]:
        """Open every registered desk, in the roadmap's order."""
        return tuple(
            self.open(session, desk, opened_by=opened_by, at=at) for desk in DESKS
        )

    def opened(self, session: Session) -> list[DeskOpening]:
        return list(
            session.execute(
                sa.select(DeskOpening).order_by(DeskOpening.desk)
            ).scalars()
        )

    def get(self, session: Session, desk: Desk | str) -> DeskOpening | None:
        key = Desk(desk) if isinstance(desk, str) else desk
        return session.execute(
            sa.select(DeskOpening).where(DeskOpening.desk == key.value)
        ).scalar_one_or_none()

    def close(
        self,
        session: Session,
        desk: Desk | str,
        *,
        reason: str,
        at: dt.datetime | None = None,
    ) -> None:
        """Shut a desk, with a reason. A desk closed without one is forgotten."""
        if not reason.strip():
            raise IntegrityViolation(
                "a desk may not be closed without a recorded reason; a desk "
                "that went quiet and one that was shut deliberately are "
                "different facts"
            )
        key = Desk(desk) if isinstance(desk, str) else desk
        row = self.get(session, key)
        if row is None:
            raise KeyError(f"the {key.value} desk was never opened")
        moment = at or self._clock.now()
        row.status = DeskStatus.CLOSED.value
        row.closed_at = moment
        row.closed_reason = reason
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.DESK_OPENED,
            actor=Actor.OPERATOR,
            subject=key.value,
            payload={"status": "closed", "reason": reason},
            at=moment,
        )
