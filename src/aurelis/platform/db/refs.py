"""Allocating human reference codes.

``AG-0042``, ``MSN-0007``, ``HYP-1842``. Monotonic per prefix, allocated from a
counter row inside the caller's transaction so a rolled-back operation does not
burn a number — an agent that was never hired should not leave a gap in the
roster, and a gap in ``HYP-`` would look like a hypothesis somebody deleted.

Codes are unique within one database, which is the right scope: they are what
people and agents cite in conversation, not join keys. Primary keys are UUIDs.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.ids import RefKind, format_ref
from aurelis.platform.db.tables import RefSequence

__all__ = ["allocate_ref", "peek_ref"]


def allocate_ref(session: Session, kind: RefKind) -> str:
    """Take the next code for ``kind``, inside the caller's transaction.

    The ``UPDATE ... RETURNING`` form makes allocation a single statement, so
    two concurrent allocations cannot read the same counter. SQLite has
    supported ``RETURNING`` since 3.35 (2021); older builds fall back to a
    read-then-write, which is safe under SQLite's single-writer model.
    """
    row = session.get(RefSequence, kind.value, with_for_update=False)
    if row is None:
        session.add(RefSequence(prefix=kind.value, next_value=1))
        session.flush()

    result = session.execute(
        sa.update(RefSequence)
        .where(RefSequence.prefix == kind.value)
        .values(next_value=RefSequence.next_value + 1)
        .returning(RefSequence.next_value)
    ).scalar_one()

    return format_ref(kind, int(result) - 1)


def peek_ref(session: Session, kind: RefKind) -> str:
    """The code the next allocation would produce. Never consumes one."""
    row = session.get(RefSequence, kind.value)
    return format_ref(kind, row.next_value if row is not None else 1)
