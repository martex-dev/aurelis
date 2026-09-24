"""Writing and reading notes in the shared brain.

A note is short on purpose: one or two sentences an agent thinks the whole
company should remember, or a thought the operator dropped into the vault.
Longer than that and it stops being read; the brain every seat carries has a
budget, and a note that crowds out five others has cost more than it said.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.brain.tables import BrainNote
from aurelis.core.canonical import sha256_of
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.platform.db.refs import allocate_ref

__all__ = [
    "NOTE_LINE",
    "leave_note",
    "NOTE_MAX",
    "NOTE_MIN",
    "OPERATOR",
    "notes_about",
    "recent_notes",
    "write_note",
]

NOTE_MIN = 12
NOTE_MAX = 400
OPERATOR = "operator"

NOTE_LINE = (
    "NOTE: <optional. One or two sentences every other agent in the company "
    "should know from what you just saw -- a trap, a pattern, a doubt. It goes "
    "into the shared brain they all read. Leave the line out if there is nothing>"
)
"""The line a seat's reply form offers. Optional: most answers leave no note."""

_EMPTY = {"none", "nothing", "n/a", "na", "-", "--", "no", "no note"}
_TOPIC = re.compile(r"^[A-Za-z0-9_.:\-]{2,96}$")


def _clean(text: str) -> str | None:
    cleaned = " ".join(str(text or "").split()).strip().strip("<>").strip()
    if len(cleaned) < NOTE_MIN or cleaned.lower().rstrip(".") in _EMPTY:
        return None
    return cleaned[:NOTE_MAX]


def write_note(
    session: Session,
    *,
    author: str,
    text: str,
    topics: tuple[str, ...] | list[str] = (),
    source_ref: str,
    ledger: Any = None,
    at: dt.datetime,
) -> BrainNote | None:
    """Add a note, or ``None`` if it says nothing or was already written.

    The same author writing the same words twice is one note: an agent that
    leaves "volume spikes on VTHO are hourly noise" on every visit has said it
    once.
    """
    cleaned = _clean(text)
    if cleaned is None:
        return None
    kept = sorted({str(t).strip() for t in topics if t and _TOPIC.match(str(t).strip())})[:8]
    digest = sha256_of({"author": author, "text": cleaned.lower()})
    if session.execute(sa.select(BrainNote.ref).where(BrainNote.digest == digest)).first():
        return None
    row = BrainNote(
        note_id=uuid7(),
        ref=allocate_ref(session, RefKind.NOTE),
        author=author,
        kind="operator" if author == OPERATOR else "agent",
        text=cleaned,
        topics=kept,
        source_ref=source_ref[:200],
        digest=digest,
        written_at=at,
    )
    session.add(row)
    session.flush()
    if ledger is not None:
        ledger.append(
            session,
            kind=EventKind.BRAIN_NOTED,
            actor=Actor.OPERATOR if author == OPERATOR else author,
            subject=row.ref,
            payload={"author": author, "topics": kept, "source": row.source_ref, "text": cleaned},
            at=at,
        )
    return row


def leave_note(
    session: Session,
    *,
    author: str,
    text: str,
    topics: tuple[str, ...] | list[str],
    source_ref: str,
    permitted: set[str],
    ledger: Any = None,
    at: dt.datetime,
) -> BrainNote | None:
    """Record the NOTE a seat's reply carried, if it says something and cites
    nothing the agent was not shown.

    A note with an invented figure is dropped, not the reply it came with: the
    view or mechanism stands on its own, and the brain does not pass a number
    nobody measured to every other agent.
    """
    from aurelis.agents.interpret import unsourced_numerals

    if not text or _clean(text) is None:
        return None
    if unsourced_numerals(text, permitted):
        return None
    return write_note(
        session,
        author=author,
        text=text,
        topics=topics,
        source_ref=source_ref,
        ledger=ledger,
        at=at,
    )


def recent_notes(session: Session, *, limit: int = 20) -> list[BrainNote]:
    return list(
        session.execute(
            sa.select(BrainNote)
            .order_by(BrainNote.written_at.desc(), BrainNote.ref.desc())
            .limit(limit)
        ).scalars()
    )


def notes_about(
    session: Session, topics: tuple[str, ...] | list[str], *, limit: int = 5
) -> list[BrainNote]:
    """The newest notes that name any of these topics, case-insensitively."""
    wanted = {str(t).lower() for t in topics if t}
    if not wanted:
        return []
    out: list[BrainNote] = []
    for note in recent_notes(session, limit=500):
        if wanted & {str(t).lower() for t in (note.topics or [])}:
            out.append(note)
            if len(out) >= limit:
                break
    return out
