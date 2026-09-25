"""A follow or a drop, once recorded, is never edited or removed.

Posts recorded from a handle are evidence only if the record also shows why
the company was reading that handle at the time. An editable follow list
would let the reason be rewritten after the posts were counted.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = ["SOCIAL_TRIGGERS", "install_social_invariants"]

SOCIAL_TRIGGERS: tuple[str, ...] = (
    "aurelis_social_target_is_immutable",
    "aurelis_social_target_never_deleted",
)

_TARGET = "Aurelis: a follow or drop is append-only. Record a new one instead."


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_social_target_is_immutable "
        "BEFORE UPDATE ON social_targets FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_TARGET}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_social_target_never_deleted "
        "BEFORE DELETE ON social_targets FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_TARGET}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_social_target_frozen() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_TARGET}'; END; $$ LANGUAGE plpgsql"
    )
    for name, verb in (
        ("aurelis_social_target_is_immutable", "UPDATE"),
        ("aurelis_social_target_never_deleted", "DELETE"),
    ):
        yield f"DROP TRIGGER IF EXISTS {name} ON social_targets"
        yield (
            f"CREATE TRIGGER {name} BEFORE {verb} ON social_targets FOR EACH ROW "
            "EXECUTE FUNCTION aurelis_social_target_frozen()"
        )


def install_social_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(f"no social invariants written for dialect {dialect!r}")
    for statement in statements:
        connection.execute(sa.text(statement))
    return SOCIAL_TRIGGERS
