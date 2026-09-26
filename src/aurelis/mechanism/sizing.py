"""How much of the paper book a scheme is given, from its record after costs (M57).

Until now every candidate scheme traded five percent of the book whatever it
had done: a scheme earning after costs by episode and one indistinguishable
from luck were sized alike, and the allocation row was written once and never
read again. Sizing is where a record turns into money, so it follows the
record, by a ladder declared here rather than a formula tuned to the past:

* **gathering, or not distinguishable from luck**: the base share, 5%;
* **earning after costs**: twice that, 10%;
* **losing after costs**: nothing (it is suspended, M55).

Schemes together never hold more than half the book, so the rest of the
company's work is never crowded out by one lucky month. Risk still assesses
every order: the share is what Portfolio asks for, not what Risk must grant.

The Portfolio Manager re-reads every scheme's record once a day and, where
the ladder says a different share, withdraws the old allocation and records
the new one with the numbers that moved it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

__all__ = [
    "BASE_WEIGHT",
    "EARNING_WEIGHT",
    "SCHEME_CAP",
    "live_allocation",
    "room_for",
    "scheme_versions",
    "target_weight",
]

BASE_WEIGHT = Decimal("0.05")
EARNING_WEIGHT = Decimal("0.10")
SCHEME_CAP = Decimal("0.50")


def target_weight(earnings: Any) -> tuple[Decimal, str]:
    """The share the ladder gives a record, and why, in words."""
    if earnings is None or not getattr(earnings, "round_trips", 0):
        return BASE_WEIGHT, "no round trip closed yet: the base share"
    if earnings.losing:
        return Decimal(0), f"losing after costs: {earnings.describe()}"
    if earnings.earning:
        return EARNING_WEIGHT, f"earning after costs: {earnings.describe()}"
    return BASE_WEIGHT, f"{earnings.verdict}: the base share. {earnings.describe()}"


def scheme_versions(session: Session) -> set[str]:
    """Every strategy version a mechanism was composed into."""
    import sqlalchemy as sa

    from aurelis.mechanism.tables import Mechanism

    return {
        str(v)
        for v in session.execute(
            sa.select(Mechanism.version_ref).where(Mechanism.version_ref.is_not(None))
        ).scalars()
    }


def live_allocation(runtime: Any, session: Session, book: str, version_ref: str) -> Any:
    return next(
        (a for a in runtime.book.allocations(session, book) if a.version_ref == version_ref),
        None,
    )


def room_for(runtime: Any, session: Session, book: str, version_ref: str) -> Decimal:
    """What is left under the cap for this version, and under the whole book."""
    schemes = scheme_versions(session)
    live = [a for a in runtime.book.allocations(session, book) if a.version_ref != version_ref]
    held_by_schemes = sum((a.weight for a in live if a.version_ref in schemes), Decimal(0))
    held = sum((a.weight for a in live), Decimal(0))
    return max(Decimal(0), min(SCHEME_CAP - held_by_schemes, Decimal(1) - held))
