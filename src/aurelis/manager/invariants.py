"""A directive is append-only (M63).

What the agents were told to do, and for how long, is part of the record. A
directive is withdrawn by a revoke row, never by editing or deleting one.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = ["DIRECTIVE_TRIGGERS", "install_directive_invariants"]

DIRECTIVE_TRIGGERS: tuple[str, ...] = (
    "aurelis_directive_is_immutable",
    "aurelis_directive_never_deleted",
)

_NOTE = "Aurelis: a directive is withdrawn by revoking it, not by editing it."


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_directive_is_immutable "
        "BEFORE UPDATE ON directives FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_NOTE}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_directive_never_deleted "
        "BEFORE DELETE ON directives FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_NOTE}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_directive_frozen() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_NOTE}'; END; $$ LANGUAGE plpgsql"
    )
    for name, verb in (
        ("aurelis_directive_is_immutable", "UPDATE"),
        ("aurelis_directive_never_deleted", "DELETE"),
    ):
        yield f"DROP TRIGGER IF EXISTS {name} ON directives"
        yield (
            f"CREATE TRIGGER {name} BEFORE {verb} ON directives FOR EACH ROW "
            "EXECUTE FUNCTION aurelis_directive_frozen()"
        )


def install_directive_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(f"no directive invariants written for dialect {dialect!r}")
    for statement in statements:
        connection.execute(sa.text(statement))
    return DIRECTIVE_TRIGGERS
