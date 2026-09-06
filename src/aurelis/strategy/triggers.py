"""The deployment invariants.

Four rules, all database triggers, all checked against raw SQL by tests. The
strategy lifecycle above them is bookkeeping if these do not hold.

``version_immutable_once_promoted``
    Once ``promoted_at`` is set, a version's spec, digest, universe, cost model
    and constraints cannot change. A material change is a **new version at
    UNDER_REVIEW**, which is what stops a validated strategy from being quietly
    improved after the evidence was gathered — and stops every result row that
    points at it from silently describing something else.

``gate_registered_before_evaluated``
    A gate's ``evaluated_at`` cannot precede its ``registered_at``. Without
    this the criterion could be written knowing the answer, which is the same
    failure preregistration exists to prevent, one layer up.

``approval_requires_matching_assessment``
    A ``TradeApproval`` must reference a ``RiskAssessment`` **of its own
    proposal**. The foreign keys already stop a dangling reference; this stops
    the subtler version, where an approval borrows some other proposal's
    assessment.

``approval_may_not_exceed_allowed``
    An approval's ``final_target`` cannot be larger than what Risk allowed. The
    service reads the number from the assessment so no caller can pass a bigger
    one, and this is the guarantee for every path that does not go through the
    service.

    Both sides are **cast before comparison**, and that is not cosmetic. Money
    is stored as text so it survives a round-trip exactly, and SQLite compares
    an integer to a string by type class rather than by value: ``12000 >
    '5000.00000000'`` is *false*, because every integer sorts before every
    string. Written the obvious way, this trigger silently permitted every
    oversized approval it was written to stop. SQLite casts to ``REAL`` and
    Postgres to ``NUMERIC``; values the service writes come from the same
    stored text on both sides, so an exactly-permitted size compares equal and
    passes.

Together these make "Risk was bypassed" and "the spec changed after validation"
unreachable rather than discouraged.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = [
    "expected_strategy_trigger_names",
    "install_strategy_invariants",
    "verify_strategy_invariants",
]

_IMMUTABLE_COLUMNS = (
    "spec_digest",
    "universe",
    "cost_model",
    "constraints",
    "desk",
)


def expected_strategy_trigger_names() -> tuple[str, ...]:
    return (
        "aurelis_approval_may_not_exceed_allowed",
        "aurelis_approval_requires_matching_assessment",
        "aurelis_gate_registered_before_evaluated",
        "aurelis_version_immutable_once_promoted",
    )


def _sqlite_statements() -> Iterator[str]:
    changed = " OR ".join(f"NEW.{column} <> OLD.{column}" for column in _IMMUTABLE_COLUMNS)
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_version_immutable_once_promoted "
        "BEFORE UPDATE ON strategy_versions FOR EACH ROW "
        f"WHEN OLD.promoted_at IS NOT NULL AND ({changed}) "
        "BEGIN SELECT RAISE(ABORT, "
        "'Aurelis: a promoted strategy version is immutable; a material change "
        "is a new version at under_review'); END"
    )

    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_gate_registered_before_evaluated "
        "BEFORE UPDATE ON promotion_gates FOR EACH ROW "
        "WHEN NEW.evaluated_at IS NOT NULL AND NEW.evaluated_at < NEW.registered_at "
        "BEGIN SELECT RAISE(ABORT, "
        "'Aurelis: a gate cannot be evaluated before its criterion was "
        "registered'); END"
    )

    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_approval_requires_matching_assessment "
        "BEFORE INSERT ON trade_approvals FOR EACH ROW "
        "WHEN NOT EXISTS ("
        "  SELECT 1 FROM risk_assessments a "
        "  WHERE a.ref = NEW.assessment_ref "
        "    AND a.proposal_ref = NEW.proposal_ref "
        "    AND a.decision IN ('allow','shrink')) "
        "BEGIN SELECT RAISE(ABORT, "
        "'Aurelis: an approval requires a permitting risk assessment of its own "
        "proposal'); END"
    )

    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_approval_may_not_exceed_allowed "
        "BEFORE INSERT ON trade_approvals FOR EACH ROW "
        "WHEN EXISTS ("
        "  SELECT 1 FROM risk_assessments a "
        "  WHERE a.ref = NEW.assessment_ref "
        "    AND CAST(NEW.final_target AS REAL) > CAST(a.allowed_exposure AS REAL)) "
        "BEGIN SELECT RAISE(ABORT, "
        "'Aurelis: an approval may not exceed the exposure Risk allowed'); END"
    )


def _postgres_statements() -> Iterator[str]:
    changed = " OR ".join(
        f"NEW.{column} IS DISTINCT FROM OLD.{column}" for column in _IMMUTABLE_COLUMNS
    )
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_version_promoted() RETURNS trigger AS $$ "
        f"BEGIN IF OLD.promoted_at IS NOT NULL AND ({changed}) THEN RAISE EXCEPTION "
        "'Aurelis: a promoted strategy version is immutable; a material change "
        "is a new version at under_review'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield (
        "DROP TRIGGER IF EXISTS aurelis_version_immutable_once_promoted "
        "ON strategy_versions"
    )
    yield (
        "CREATE TRIGGER aurelis_version_immutable_once_promoted BEFORE UPDATE ON "
        "strategy_versions FOR EACH ROW EXECUTE FUNCTION aurelis_check_version_promoted()"
    )

    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_gate_order() RETURNS trigger AS $$ "
        "BEGIN IF NEW.evaluated_at IS NOT NULL AND NEW.evaluated_at < "
        "NEW.registered_at THEN RAISE EXCEPTION "
        "'Aurelis: a gate cannot be evaluated before its criterion was registered'; "
        "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_gate_registered_before_evaluated ON promotion_gates"
    yield (
        "CREATE TRIGGER aurelis_gate_registered_before_evaluated BEFORE UPDATE ON "
        "promotion_gates FOR EACH ROW EXECUTE FUNCTION aurelis_check_gate_order()"
    )

    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_approval_assessment() RETURNS trigger AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM risk_assessments a WHERE a.ref = "
        "NEW.assessment_ref AND a.proposal_ref = NEW.proposal_ref AND a.decision "
        "IN ('allow','shrink')) THEN RAISE EXCEPTION "
        "'Aurelis: an approval requires a permitting risk assessment of its own "
        "proposal'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield (
        "DROP TRIGGER IF EXISTS aurelis_approval_requires_matching_assessment "
        "ON trade_approvals"
    )
    yield (
        "CREATE TRIGGER aurelis_approval_requires_matching_assessment BEFORE INSERT ON "
        "trade_approvals FOR EACH ROW EXECUTE FUNCTION aurelis_check_approval_assessment()"
    )

    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_approval_size() RETURNS trigger AS $$ "
        "BEGIN IF EXISTS (SELECT 1 FROM risk_assessments a WHERE a.ref = "
        "NEW.assessment_ref AND CAST(NEW.final_target AS NUMERIC) > "
        "CAST(a.allowed_exposure AS NUMERIC)) THEN "
        "RAISE EXCEPTION 'Aurelis: an approval may not exceed the exposure Risk "
        "allowed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_approval_may_not_exceed_allowed ON trade_approvals"
    yield (
        "CREATE TRIGGER aurelis_approval_may_not_exceed_allowed BEFORE INSERT ON "
        "trade_approvals FOR EACH ROW EXECUTE FUNCTION aurelis_check_approval_size()"
    )


def install_strategy_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Install the deployment triggers. Idempotent."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no deployment invariants written for dialect {dialect!r}. Aurelis "
            "will not run a strategy layer without them: bypassing Risk has to "
            "be impossible, not merely discouraged."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return expected_strategy_trigger_names()


def verify_strategy_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Return the expected triggers that are **missing**."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        )
    elif dialect == "postgresql":
        rows = connection.execute(
            sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        )
    else:  # pragma: no cover
        raise NotImplementedError(dialect)
    installed = {str(row[0]) for row in rows}
    return tuple(
        name for name in expected_strategy_trigger_names() if name not in installed
    )
