"""A note in the shared brain is append-only.

Every agent that sat after a note was written was shown it. Editing or
deleting it afterwards would change what they were shown, after the fact.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = ["BRAIN_TRIGGERS", "install_brain_invariants"]

BRAIN_TRIGGERS: tuple[str, ...] = (
    "aurelis_brain_note_is_immutable",
    "aurelis_brain_note_never_deleted",
)

_NOTE = "Aurelis: a note in the shared brain is append-only. Others were shown it."


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_brain_note_is_immutable "
        "BEFORE UPDATE ON brain_notes FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_NOTE}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_brain_note_never_deleted "
        "BEFORE DELETE ON brain_notes FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_NOTE}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_brain_note_frozen() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_NOTE}'; END; $$ LANGUAGE plpgsql"
    )
    for name, verb in (
        ("aurelis_brain_note_is_immutable", "UPDATE"),
        ("aurelis_brain_note_never_deleted", "DELETE"),
    ):
        yield f"DROP TRIGGER IF EXISTS {name} ON brain_notes"
        yield (
            f"CREATE TRIGGER {name} BEFORE {verb} ON brain_notes FOR EACH ROW "
            "EXECUTE FUNCTION aurelis_brain_note_frozen()"
        )


def install_brain_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(f"no brain invariants written for dialect {dialect!r}")
    for statement in statements:
        connection.execute(sa.text(statement))
    return BRAIN_TRIGGERS
