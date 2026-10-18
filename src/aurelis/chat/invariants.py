"""A conversation is append-only (M62).

What an agent told the operator is part of the record of that agent. Editing
it afterwards would rewrite what the operator was told.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = ["CHAT_TRIGGERS", "install_chat_invariants"]

CHAT_TRIGGERS: tuple[str, ...] = (
    "aurelis_chat_turn_is_immutable",
    "aurelis_chat_turn_never_deleted",
)

_NOTE = "Aurelis: a conversation is append-only. What was said was said."


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_chat_turn_is_immutable "
        "BEFORE UPDATE ON chat_turns FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_NOTE}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_chat_turn_never_deleted "
        "BEFORE DELETE ON chat_turns FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_NOTE}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_chat_turn_frozen() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_NOTE}'; END; $$ LANGUAGE plpgsql"
    )
    for name, verb in (
        ("aurelis_chat_turn_is_immutable", "UPDATE"),
        ("aurelis_chat_turn_never_deleted", "DELETE"),
    ):
        yield f"DROP TRIGGER IF EXISTS {name} ON chat_turns"
        yield (
            f"CREATE TRIGGER {name} BEFORE {verb} ON chat_turns FOR EACH ROW "
            "EXECUTE FUNCTION aurelis_chat_turn_frozen()"
        )


def install_chat_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(f"no chat invariants written for dialect {dialect!r}")
    for statement in statements:
        connection.execute(sa.text(statement))
    return CHAT_TRIGGERS
