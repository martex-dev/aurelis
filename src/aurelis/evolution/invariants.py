"""A method, once adopted, is never edited or removed.

The views an agent sealed under a method are scored against that method. If
the method could be edited afterwards, the record would score views against
words the agent was never given.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = ["EVOLUTION_TRIGGERS", "install_evolution_invariants"]

EVOLUTION_TRIGGERS: tuple[str, ...] = (
    "aurelis_agent_method_is_immutable",
    "aurelis_agent_method_never_deleted",
)

_METHOD = "Aurelis: an adopted method is append-only. Views were sealed under it."


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_agent_method_is_immutable "
        "BEFORE UPDATE ON agent_methods FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_METHOD}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_agent_method_never_deleted "
        "BEFORE DELETE ON agent_methods FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_METHOD}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_agent_method_frozen() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_METHOD}'; END; $$ LANGUAGE plpgsql"
    )
    for name, verb in (
        ("aurelis_agent_method_is_immutable", "UPDATE"),
        ("aurelis_agent_method_never_deleted", "DELETE"),
    ):
        yield f"DROP TRIGGER IF EXISTS {name} ON agent_methods"
        yield (
            f"CREATE TRIGGER {name} BEFORE {verb} ON agent_methods FOR EACH ROW "
            "EXECUTE FUNCTION aurelis_agent_method_frozen()"
        )


def install_evolution_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(f"no evolution invariants written for dialect {dialect!r}")
    for statement in statements:
        connection.execute(sa.text(statement))
    return EVOLUTION_TRIGGERS
