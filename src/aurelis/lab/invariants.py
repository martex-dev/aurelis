"""The strategy lab is append-only (M65).

A lab result is what the company learned about a taught strategy. A later
run adds rows; it never rewrites what an earlier one found.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = ["LAB_TRIGGERS", "install_lab_invariants"]

LAB_TRIGGERS: tuple[str, ...] = (
    "aurelis_lab_result_is_immutable",
    "aurelis_lab_result_never_deleted",
)

_NOTE = "Aurelis: a lab result once recorded is not rewritten."


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_lab_result_is_immutable "
        "BEFORE UPDATE ON lab_results FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_NOTE}'); END"
    )
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_lab_result_never_deleted "
        "BEFORE DELETE ON lab_results FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{_NOTE}'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_lab_result_frozen() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_NOTE}'; END; $$ LANGUAGE plpgsql"
    )
    for name, verb in (
        ("aurelis_lab_result_is_immutable", "UPDATE"),
        ("aurelis_lab_result_never_deleted", "DELETE"),
    ):
        yield f"DROP TRIGGER IF EXISTS {name} ON lab_results"
        yield (
            f"CREATE TRIGGER {name} BEFORE {verb} ON lab_results FOR EACH ROW "
            "EXECUTE FUNCTION aurelis_lab_result_frozen()"
        )


def install_lab_invariants(connection: sa.Connection) -> tuple[str, ...]:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(f"no lab invariants written for dialect {dialect!r}")
    for statement in statements:
        connection.execute(sa.text(statement))
    return LAB_TRIGGERS
