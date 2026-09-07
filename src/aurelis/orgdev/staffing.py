"""Staffing a desk, through the mechanism that decides everything else.

M12 opened six desks and hired nobody for any of them, which the roadmap noted
as real work left undone. This is that work — and the point is *how* it is
done. Inserting eighty agent rows would take an afternoon and would be exactly
the anti-pattern `CLAUDE.md` §34 names: creating hundreds of agents before the
evidence justifies them.

So the desks are staffed by the M11 machinery. A measured condition fires a
declared trigger; a proposal is written carrying the measurement; the
prediction is hashed before the Board sees it; the room decides; the change is
applied; and the effect is measured against the locked prediction. The company
grows the same way it does anything else, and the record says whether it
worked.

The measured condition is new and it is the honest one. ``DESK_UNSTAFFED``
fires when a desk is open and slots that only exist because it is open are held
by nobody. That is not a hunch: opening the Options desk created thirteen jobs
(:mod:`aurelis.org.slots`), and thirteen jobs with nobody in them is a fact
about the org chart that can be counted.

**How much staff a desk gets is deliberately conservative.** Each new desk is
staffed the way the launch roster staffed crypto: one generalist per department
that has desk-specific charters, so five agents. Not thirteen specialists —
there is no load on a desk running on fixtures, and hiring a specialist per
charter would be assuming that more agents is better, which is precisely what
the company is built to stop assuming.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.errors import IntegrityViolation
from aurelis.org.charters import CHARTERS, Seniority
from aurelis.org.departments import Department
from aurelis.org.desks import Desk
from aurelis.org.slots import Slot, census
from aurelis.orgdev.detection import OrgTrigger, TriggerHit
from aurelis.orgdev.metrics import Reading
from aurelis.orgdev.states import OrgChangeKind, TriggerKind

__all__ = [
    "DESK_UNSTAFFED",
    "DeskStaffing",
    "unstaffed_desks",
    "staffing_plan",
]

DESK_UNSTAFFED = OrgTrigger(
    TriggerKind.DESK_OPENED,
    "unstaffed_slots",
    "gte",
    Decimal(1),
    OrgChangeKind.HIRE,
    asks=(
        "Is this desk open with jobs on it that nobody holds? Opening a desk "
        "creates one slot per desk-specific charter, and an open desk with "
        "nobody on it produces nothing while looking staffed in the roster."
    ),
)
"""The measured condition M12 left behind.

Not a reminder that the desks need people. A count of slots that exist because
a desk was opened and that nobody holds.
"""


#: Handle prefixes per department, so a desk's team reads like the launch
#: roster's. INTEL-OPT is recognisably the Options Intelligence generalist.
_PREFIX: dict[Department, str] = {
    Department.MARKET_INTELLIGENCE: "INTEL",
    Department.QUANTITATIVE_RESEARCH: "QUANT",
    Department.STRATEGY_LABORATORY: "STRAT",
    Department.PORTFOLIO_AND_RISK: "RISK",
    Department.TRADING_OPERATIONS: "TRADE",
}

_SUFFIX: dict[Desk, str] = {
    Desk.CRYPTO: "CR",
    Desk.EQUITIES: "EQ",
    Desk.OPTIONS: "OPT",
    Desk.FUTURES: "FUT",
    Desk.COMMODITIES: "COM",
    Desk.FX: "FX",
    Desk.MEMECOIN: "MEME",
}


@dataclass(frozen=True, slots=True)
class DeskStaffing:
    """One agent to hire, and the slots it would take."""

    handle: str
    department: Department
    desk: Desk
    charters: tuple[str, ...]
    seniority: Seniority = Seniority.SENIOR

    @property
    def slots(self) -> tuple[Slot, ...]:
        return tuple(Slot(c, self.desk.value) for c in self.charters)

    def as_payload(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "department": self.department.value,
            "desk": self.desk.value,
            "charters": list(self.charters),
        }

    def describe(self) -> str:
        return (
            f"{self.handle}: {len(self.charters)} charter(s) on "
            f"{self.desk.value}"
        )


def staffing_plan(session: Session, desk: Desk | str) -> tuple[DeskStaffing, ...]:
    """Who this desk needs, grouped the way the launch roster grouped crypto.

    One generalist per department that has unheld desk-specific charters here.
    Deliberately not one specialist per charter: a desk running on fixtures
    generates no load, and hiring thirteen people for it would be assuming that
    headcount is capability -- the assumption M11 measured and found false.
    """
    key = Desk(desk) if isinstance(desk, str) else desk
    open_slots = [s for s in census(session).unstaffed if s.desk == key.value]
    if not open_slots:
        return ()

    by_department: dict[Department, list[str]] = defaultdict(list)
    for slot in sorted(open_slots):
        by_department[CHARTERS[slot.charter_id].department].append(slot.charter_id)

    plan: list[DeskStaffing] = []
    for department, charters in sorted(by_department.items(), key=lambda kv: kv[0].value):
        prefix = _PREFIX.get(department)
        if prefix is None:
            raise IntegrityViolation(
                f"{department.value} has desk-specific charters on "
                f"{key.value} and no handle prefix; a desk team whose members "
                "cannot be named is not a plan"
            )
        plan.append(
            DeskStaffing(
                handle=f"{prefix}-{_SUFFIX[key]}",
                department=department,
                desk=key,
                charters=tuple(charters),
            )
        )
    return tuple(plan)


def unstaffed_desks(session: Session) -> tuple[TriggerHit, ...]:
    """Every open desk with jobs nobody holds, as trigger hits.

    Shaped as :class:`TriggerHit` so it goes through exactly the same proposal
    path as a fission: the measurement travels with the proposal, and a change
    without one cannot be written.
    """
    taken = census(session)
    per_desk: dict[str, list[Slot]] = defaultdict(list)
    for slot in taken.unstaffed:
        if not slot.company_wide:
            per_desk[slot.desk].append(slot)

    hits: list[TriggerHit] = []
    for desk_value, slots in sorted(per_desk.items()):
        reading = Reading(
            metric="unstaffed_slots",
            value=Decimal(len(slots)),
            detail=(
                f"{len(slots)} slot(s) on the open {desk_value} desk are held "
                f"by nobody: {', '.join(s.charter_id for s in sorted(slots))}"
            ),
        )
        hits.append(
            TriggerHit(
                trigger=DESK_UNSTAFFED,
                subject=desk_value,
                handle=desk_value,
                reading=reading,
            )
        )
    return tuple(hits)


def hire_for(
    runtime: Any,
    session: Session,
    entry: DeskStaffing,
    *,
    hired_by: str,
    at: dt.datetime | None = None,
) -> str:
    """Put one desk generalist on the roster, holding its desk's slots."""
    agent = runtime.roster.hire(
        session,
        handle=entry.handle,
        department=entry.department,
        coverage=entry.charters,
        seniority=entry.seniority,
        desk=entry.desk,
        hired_by=hired_by,
        note=(
            f"Desk generalist for {entry.desk.value}. Holds "
            f"{len(entry.charters)} desk-specific charter(s), the way the "
            "launch roster held crypto's."
        ),
        at=at,
    )
    return str(agent.ref)
