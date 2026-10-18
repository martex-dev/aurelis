"""Standing directives: the operator's instructions, in every seat (M63).

The operator tells the Manager what they want; the Manager writes it down as
a directive. Every agent then reads the active directives in the shared brain
at every seat, beside the record and the notes. That is how an instruction
becomes work in this company: not by a new code path for each wish, but by
changing what every agent is told when it next chooses what to look at,
what to believe and what to say.

A directive guides; it does not override. It cannot open a market the
company has no data for, lift a Risk limit, skip the figure guard or turn on
real money. The Manager is told so, and tells the operator so.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.enums import EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.manager.tables import Directive
from aurelis.platform.db.refs import allocate_ref

__all__ = ["Active", "active", "directive_block", "issue", "revoke"]

_BUDGET = 700
"""Characters of directives every seat carries. Over it, the newest are kept."""


@dataclass(frozen=True, slots=True)
class Active:
    ref: str
    text: str
    audience: tuple[str, ...]
    issued_at: dt.datetime

    def for_whom(self) -> str:
        return "everyone" if "all" in self.audience else ", ".join(self.audience)


def active(session: Session) -> list[Active]:
    """Every directive issued and not revoked, newest first."""
    revoked = set(
        session.execute(sa.select(Directive.revokes).where(Directive.kind == "revoke")).scalars()
    )
    rows = session.execute(
        sa.select(Directive)
        .where(Directive.kind == "issue")
        .order_by(Directive.issued_at.desc(), Directive.ref.desc())
    ).scalars()
    return [
        Active(r.ref, r.text, tuple(str(a) for a in (r.audience or ["all"])), r.issued_at)
        for r in rows
        if r.ref not in revoked
    ]


def issue(
    session: Session,
    ledger: object,
    *,
    text: str,
    audience: tuple[str, ...],
    manager_ref: str,
    because: str,
    at: dt.datetime,
) -> Directive:
    row = Directive(
        directive_id=uuid7(),
        ref=allocate_ref(session, RefKind.DIRECTIVE),
        kind="issue",
        text=text.strip()[:600],
        audience=list(audience) or ["all"],
        revokes=None,
        issued_by=manager_ref,
        because=because,
        issued_at=at,
    )
    session.add(row)
    session.flush()
    ledger.append(  # type: ignore[attr-defined]
        session,
        kind=EventKind.DIRECTIVE_ISSUED,
        actor=manager_ref,
        subject=row.ref,
        payload={"text": row.text[:300], "audience": row.audience, "because": because},
        at=at,
    )
    return row


def revoke(
    session: Session,
    ledger: object,
    *,
    ref: str,
    manager_ref: str,
    because: str,
    at: dt.datetime,
) -> Directive | None:
    """Withdraw an active directive; ``None`` if there is no such active one."""
    if ref not in {a.ref for a in active(session)}:
        return None
    row = Directive(
        directive_id=uuid7(),
        ref=allocate_ref(session, RefKind.DIRECTIVE),
        kind="revoke",
        text="",
        audience=[],
        revokes=ref,
        issued_by=manager_ref,
        because=because,
        issued_at=at,
    )
    session.add(row)
    session.flush()
    ledger.append(  # type: ignore[attr-defined]
        session,
        kind=EventKind.DIRECTIVE_REVOKED,
        actor=manager_ref,
        subject=ref,
        payload={"by": row.ref, "because": because},
        at=at,
    )
    return row


def directive_block(session: Session) -> str:
    """The active directives as the lines every seat reads, or ``""``."""
    lines: list[str] = []
    used = 0
    for item in active(session):
        line = f"- {item.ref} (for {item.for_whom()}): {item.text}"
        if used + len(line) > _BUDGET:
            lines.append("  (older directives cut for length)")
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)
