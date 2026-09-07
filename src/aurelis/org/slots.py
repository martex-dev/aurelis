"""Coverage is two-dimensional: a charter, on a desk.

ADR-0004 said desks are the company's second organisational dimension and that
an agent is ``(charter, desk)``. Until M13 only half of that was true. A
``Charter`` carried ``desk_specific`` and nothing read it, and coverage was a
flat set of charter ids — so a Technical Analyst was one person for the whole
company, and opening the Options desk gave that person a seventh market rather
than giving the desk an analyst.

A **slot** is the unit that fixes it:

``(charter, desk)``
    for a charter that is meaningfully different per market. A Technical
    Analyst on Options and one on FX share a remit and differ in tools, data,
    cost models and playbooks, so they are two jobs.

``(charter, "")``
    for everything else. There is one Company Manager, one Registrar, one
    Ledger Officer, and giving each desk its own would be inventing work.

Thirteen of the seventy-six charters are desk-specific. With seven desks open
that is ``13 x 7 + 63 = 154`` slots — which is where the roadmap's "100+
agents" actually comes from, and why it was unreachable while coverage was
flat.

**The required set depends on which desks are open**, which is the point.
Opening a desk creates thirteen unstaffed slots, and that is a measured
condition rather than a reminder in a document: :func:`unstaffed` returns them
and the M11 trigger table fires on the result.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.org.charters import CHARTERS, Charter
from aurelis.org.desks import Desk

__all__ = [
    "COMPANY_WIDE",
    "CoverageCensus",
    "Slot",
    "census",
    "desk_for_charter",
    "held_slots",
    "required_slots",
    "slots_for_charters",
    "unstaffed",
]

COMPANY_WIDE = ""
"""The desk value for a charter that is not desk-specific.

An empty string rather than NULL, because this is part of a composite primary
key and NULL does not compare equal to itself. A company-wide charter has
exactly one holder and its slot says so plainly.
"""


@dataclass(frozen=True, slots=True, order=True)
class Slot:
    """One job: a charter, and the desk it is held for."""

    charter_id: str
    desk: str = COMPANY_WIDE

    @property
    def company_wide(self) -> bool:
        return self.desk == COMPANY_WIDE

    @property
    def charter(self) -> Charter:
        return CHARTERS[self.charter_id]

    def as_payload(self) -> dict[str, Any]:
        return {"charter_id": self.charter_id, "desk": self.desk}

    def describe(self) -> str:
        return self.charter_id if self.company_wide else f"{self.charter_id}@{self.desk}"


def desk_for_charter(charter_id: str, desk: str | Desk | None) -> str:
    """Which desk value a coverage row for this charter should carry.

    A desk-specific charter held by an agent with no desk is a contradiction:
    somebody has to be the Technical Analyst *for* somewhere. It raises rather
    than defaulting, because defaulting would silently put every desk-specific
    charter on one nameless desk and the census would then read as complete.
    """
    charter = CHARTERS.get(charter_id)
    if charter is None:
        raise KeyError(f"no charter {charter_id!r}")
    if not charter.desk_specific:
        return COMPANY_WIDE
    value = desk.value if isinstance(desk, Desk) else (desk or "")
    if not value:
        raise ValueError(
            f"{charter_id} is desk-specific: it is a different job on every "
            "market, so a holder must say which desk it holds it for"
        )
    return value


def slots_for_charters(
    charters: Iterable[str], desk: str | Desk | None
) -> tuple[Slot, ...]:
    """The slots an agent on ``desk`` occupies by holding ``charters``."""
    return tuple(
        Slot(charter_id, desk_for_charter(charter_id, desk))
        for charter_id in charters
    )


def required_slots(open_desks: Iterable[str | Desk]) -> frozenset[Slot]:
    """Every job the company owes somebody, given which desks are open."""
    desks = [d.value if isinstance(d, Desk) else d for d in open_desks]
    found: set[Slot] = set()
    for charter_id, charter in CHARTERS.items():
        if charter.desk_specific:
            found.update(Slot(charter_id, desk) for desk in desks)
        else:
            found.add(Slot(charter_id, COMPANY_WIDE))
    return frozenset(found)


def held_slots(session: Session) -> dict[Slot, list[str]]:
    """Who currently holds what. A list, so double-holding is visible."""
    from aurelis.agents.tables import Agent, AgentCoverage, AgentState

    rows = session.execute(
        sa.select(AgentCoverage.charter_id, AgentCoverage.desk, AgentCoverage.agent_ref)
        .join(Agent, Agent.ref == AgentCoverage.agent_ref)
        .where(Agent.state != AgentState.RETIRED)
    ).all()
    held: dict[Slot, list[str]] = {}
    for charter_id, desk, agent_ref in rows:
        held.setdefault(Slot(str(charter_id), str(desk)), []).append(str(agent_ref))
    return held


@dataclass(frozen=True, slots=True)
class CoverageCensus:
    """Every slot the company owes, and whether somebody holds it."""

    required: frozenset[Slot]
    held: dict[Slot, list[str]]

    @property
    def unstaffed(self) -> tuple[Slot, ...]:
        return tuple(sorted(self.required - set(self.held)))

    @property
    def duplicated(self) -> tuple[Slot, ...]:
        return tuple(sorted(s for s, who in self.held.items() if len(who) > 1))

    @property
    def unrequired(self) -> tuple[Slot, ...]:
        """Held slots the registry does not ask for — a closed desk's staff."""
        return tuple(sorted(set(self.held) - self.required))

    @property
    def intact(self) -> bool:
        """Every required slot held exactly once, and nothing held twice."""
        return not self.unstaffed and not self.duplicated

    @property
    def coverage(self) -> str:
        return f"{len(self.required) - len(self.unstaffed)}/{len(self.required)}"

    def by_desk(self) -> dict[str, tuple[int, int]]:
        """Held and required, per desk. ``""`` is the company-wide row."""
        out: dict[str, tuple[int, int]] = {}
        for slot in self.required:
            held, needed = out.get(slot.desk, (0, 0))
            out[slot.desk] = (held + (1 if slot in self.held else 0), needed + 1)
        return dict(sorted(out.items()))

    def as_payload(self) -> dict[str, Any]:
        return {
            "required": len(self.required),
            "held": len(self.held),
            "unstaffed": [s.describe() for s in self.unstaffed],
            "duplicated": [s.describe() for s in self.duplicated],
            "intact": self.intact,
        }

    def describe(self) -> str:
        if self.intact:
            return f"{self.coverage} slots held, exactly once each"
        problems = []
        if self.unstaffed:
            problems.append(f"{len(self.unstaffed)} unstaffed")
        if self.duplicated:
            problems.append(f"{len(self.duplicated)} held twice")
        return f"{self.coverage} slots held; " + ", ".join(problems)


def census(session: Session, open_desks: Iterable[str | Desk] | None = None) -> CoverageCensus:
    """Compare what the company owes against what it has staffed."""
    if open_desks is None:
        open_desks = _open_desks(session)
    return CoverageCensus(
        required=required_slots(open_desks), held=held_slots(session)
    )


def unstaffed(
    session: Session, open_desks: Iterable[str | Desk] | None = None
) -> tuple[Slot, ...]:
    """Jobs nobody is doing. What the DESK_UNSTAFFED trigger fires on."""
    return census(session, open_desks).unstaffed


def _open_desks(session: Session) -> tuple[str, ...]:
    """Desks the company has actually opened, from the record.

    Read from ``desk_openings`` rather than from the registry's status field:
    a desk is open because the checklist let it open, not because a constant
    says so.
    """
    from aurelis.desks.tables import DeskOpening

    rows = tuple(
        session.execute(
            sa.select(DeskOpening.desk).where(DeskOpening.status == "active")
        ).scalars()
    )
    return rows or (Desk.CRYPTO.value,)
