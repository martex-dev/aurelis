"""Events and relations are append-only.

An event that could be edited is a fact the company can change its mind about
having learned; a relation that could be deleted is a link the graph once had
and now denies. Both are refused by the database. An entity's attributes may
change — that is what an entity is — and every change is itself an event.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = ["WORLD_TRIGGERS", "install_world_invariants", "verify_world_invariants"]

WORLD_TRIGGERS: tuple[str, ...] = (
    "aurelis_world_event_is_immutable",
    "aurelis_world_event_never_deleted",
    "aurelis_relation_is_immutable",
    "aurelis_relation_never_deleted",
)

_EVENT = "Aurelis: a world event is immutable. What the company learned is what it learned."
_RELATION = "Aurelis: a relation is append-only. A link the graph once had is not denied."


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_world_event_is_immutable "
        "BEFORE UPDATE ON world_events FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_EVENT}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_world_event_never_deleted "
        "BEFORE DELETE ON world_events FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_EVENT}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_relation_is_immutable "
        "BEFORE UPDATE ON relations FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_RELATION}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_relation_never_deleted "
        "BEFORE DELETE ON relations FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_RELATION}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_world_event_frozen() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_EVENT}'; END; $$ LANGUAGE plpgsql"
    )
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_relation_frozen() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_RELATION}'; END; $$ LANGUAGE plpgsql"
    )
    for name, table, verb, function in (
        (
            "aurelis_world_event_is_immutable",
            "world_events",
            "UPDATE",
            "aurelis_world_event_frozen",
        ),
        (
            "aurelis_world_event_never_deleted",
            "world_events",
            "DELETE",
            "aurelis_world_event_frozen",
        ),
        ("aurelis_relation_is_immutable", "relations", "UPDATE", "aurelis_relation_frozen"),
        ("aurelis_relation_never_deleted", "relations", "DELETE", "aurelis_relation_frozen"),
    ):
        yield f"DROP TRIGGER IF EXISTS {name} ON {table}"
        yield (
            f"CREATE TRIGGER {name} BEFORE {verb} ON {table} FOR EACH ROW "
            f"EXECUTE FUNCTION {function}()"
        )


def install_world_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(f"no world invariants written for dialect {dialect!r}")
    for statement in statements:
        connection.execute(sa.text(statement))
    return WORLD_TRIGGERS


def verify_world_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))
    elif dialect == "postgresql":
        rows = connection.execute(sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))
    else:  # pragma: no cover - guarded by install
        raise NotImplementedError(dialect)
    installed = {str(row[0]) for row in rows}
    return tuple(name for name in WORLD_TRIGGERS if name not in installed)
