"""The preregistration invariants.

Three rules, all database triggers, all checked against raw SQL by tests. This
is the milestone's centre of gravity: everything else in the research lifecycle
is bookkeeping if these do not hold.

``run_requires_prior_registration``
    A ``Run`` cannot be inserted unless a **locked** registration for it exists
    and was locked *strictly before* the run started. Not merely "exists" —
    before. A registration locked after the fact would satisfy a weaker check
    while providing exactly none of the protection.

``registration_immutable_once_locked``
    Once ``locked_at`` is set, the spec, criteria, seed, kind and declared
    cells cannot change. A revised design is a new row that supersedes this
    one and is degraded to exploratory. This is what stops a disappointing
    confirmatory test from being quietly re-aimed at whatever it did find.

``result_requires_a_completed_run``
    A measurement cannot exist without a run that completed. Combined with the
    ``computed_by`` CHECK on the table itself, there is no path by which a
    number enters the record without a computation behind it.

Together these make HARKing unreachable rather than discouraged. An agent
cannot decide what counts as success after seeing results, because the criteria
were hashed and frozen before the run was allowed to exist.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = [
    "expected_research_trigger_names",
    "install_research_invariants",
    "verify_research_invariants",
]

_IMMUTABLE_COLUMNS = ("spec_digest", "pass_criteria", "seed", "kind", "declared_cells")


def expected_research_trigger_names() -> tuple[str, ...]:
    return (
        "aurelis_registration_immutable_once_locked",
        "aurelis_result_requires_completed_run",
        "aurelis_run_requires_prior_registration",
    )


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_run_requires_prior_registration "
        "BEFORE INSERT ON runs FOR EACH ROW "
        "WHEN NOT EXISTS ("
        "  SELECT 1 FROM registrations r "
        "  WHERE r.ref = NEW.registration_ref "
        "    AND r.locked_at IS NOT NULL "
        "    AND r.locked_at <= NEW.started_at) "
        "BEGIN SELECT RAISE(ABORT, "
        "'Aurelis: a run requires a registration locked before it started'); END"
    )

    changed = " OR ".join(f"NEW.{column} <> OLD.{column}" for column in _IMMUTABLE_COLUMNS)
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_registration_immutable_once_locked "
        "BEFORE UPDATE ON registrations FOR EACH ROW "
        f"WHEN OLD.locked_at IS NOT NULL AND ({changed}) "
        "BEGIN SELECT RAISE(ABORT, "
        "'Aurelis: a locked registration is immutable; revise by superseding it'); END"
    )

    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_result_requires_completed_run "
        "BEFORE INSERT ON results FOR EACH ROW "
        "WHEN NOT EXISTS ("
        "  SELECT 1 FROM runs u WHERE u.ref = NEW.run_ref AND u.status = 'completed') "
        "BEGIN SELECT RAISE(ABORT, "
        "'Aurelis: a result requires a completed run'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_prior_registration() RETURNS trigger AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM registrations r WHERE r.ref = "
        "NEW.registration_ref AND r.locked_at IS NOT NULL AND r.locked_at <= "
        "NEW.started_at) THEN RAISE EXCEPTION "
        "'Aurelis: a run requires a registration locked before it started'; "
        "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_run_requires_prior_registration ON runs"
    yield (
        "CREATE TRIGGER aurelis_run_requires_prior_registration BEFORE INSERT ON runs "
        "FOR EACH ROW EXECUTE FUNCTION aurelis_check_prior_registration()"
    )

    changed = " OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in _IMMUTABLE_COLUMNS
    )
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_registration_locked() RETURNS trigger AS $$ "
        f"BEGIN IF OLD.locked_at IS NOT NULL AND ({changed}) THEN RAISE EXCEPTION "
        "'Aurelis: a locked registration is immutable; revise by superseding it'; "
        "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield (
        "DROP TRIGGER IF EXISTS aurelis_registration_immutable_once_locked ON registrations"
    )
    yield (
        "CREATE TRIGGER aurelis_registration_immutable_once_locked BEFORE UPDATE ON "
        "registrations FOR EACH ROW EXECUTE FUNCTION aurelis_check_registration_locked()"
    )

    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_run_completed() RETURNS trigger AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM runs u WHERE u.ref = NEW.run_ref AND "
        "u.status = 'completed') THEN RAISE EXCEPTION "
        "'Aurelis: a result requires a completed run'; END IF; RETURN NEW; END; "
        "$$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_result_requires_completed_run ON results"
    yield (
        "CREATE TRIGGER aurelis_result_requires_completed_run BEFORE INSERT ON results "
        "FOR EACH ROW EXECUTE FUNCTION aurelis_check_run_completed()"
    )


def install_research_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Install the preregistration triggers. Idempotent."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no preregistration invariants written for dialect {dialect!r}. "
            "Aurelis will not run research without them: HARKing has to be "
            "impossible, not merely discouraged."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return expected_research_trigger_names()


def verify_research_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Return the expected triggers that are **missing**."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        )
    elif dialect == "postgresql":
        rows = connection.execute(sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))
    else:  # pragma: no cover
        raise NotImplementedError(dialect)
    installed = {str(row[0]) for row in rows}
    return tuple(
        name for name in expected_research_trigger_names() if name not in installed
    )
