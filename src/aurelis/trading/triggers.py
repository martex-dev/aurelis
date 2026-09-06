"""The execution invariants.

Two rules, both database triggers, both checked against raw SQL by tests.

``order_requires_intact_approval``
    An order's approval must exist *and* still cite a permitting risk
    assessment of its own proposal. The foreign key already stops a dangling
    reference; this stops the case where an approval row exists but the chain
    behind it does not hold — which is what an attacker, or a careless
    migration, would actually produce.

``order_may_not_exceed_approval``
    An order's notional cannot exceed what was approved. The service enforces
    it too, but the service is one path and this is every path.

Both comparisons **cast before comparing**. Money is stored as text so it
round-trips exactly, and SQLite orders an integer before any string — the same
trap that made M8's oversize guard silently permit everything it was written to
stop. Once was enough; the cast is now the habit.
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlalchemy as sa

__all__ = [
    "expected_trading_trigger_names",
    "install_trading_invariants",
    "verify_trading_invariants",
]


def expected_trading_trigger_names() -> tuple[str, ...]:
    return (
        "aurelis_order_may_not_exceed_approval",
        "aurelis_order_requires_intact_approval",
    )


def _sqlite_statements() -> Iterator[str]:
    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_order_requires_intact_approval "
        "BEFORE INSERT ON orders FOR EACH ROW "
        "WHEN NOT EXISTS ("
        "  SELECT 1 FROM trade_approvals ap "
        "  JOIN risk_assessments a ON a.ref = ap.assessment_ref "
        "  WHERE ap.ref = NEW.approval_ref "
        "    AND a.proposal_ref = ap.proposal_ref "
        "    AND a.decision IN ('allow','shrink')) "
        "BEGIN SELECT RAISE(ABORT, "
        "'Aurelis: an order requires an approval backed by a permitting risk "
        "assessment of its own proposal'); END"
    )

    yield (
        "CREATE TRIGGER IF NOT EXISTS aurelis_order_may_not_exceed_approval "
        "BEFORE INSERT ON orders FOR EACH ROW "
        "WHEN EXISTS ("
        "  SELECT 1 FROM trade_approvals ap "
        "  WHERE ap.ref = NEW.approval_ref "
        "    AND CAST(NEW.quantity AS REAL) * CAST(NEW.expected_price AS REAL) "
        "        > CAST(ap.final_target AS REAL)) "
        "BEGIN SELECT RAISE(ABORT, "
        "'Aurelis: an order may not exceed the notional Risk approved'); END"
    )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_order_approval() RETURNS trigger AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM trade_approvals ap JOIN risk_assessments a "
        "ON a.ref = ap.assessment_ref WHERE ap.ref = NEW.approval_ref AND "
        "a.proposal_ref = ap.proposal_ref AND a.decision IN ('allow','shrink')) "
        "THEN RAISE EXCEPTION 'Aurelis: an order requires an approval backed by a "
        "permitting risk assessment of its own proposal'; END IF; RETURN NEW; END; "
        "$$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_order_requires_intact_approval ON orders"
    yield (
        "CREATE TRIGGER aurelis_order_requires_intact_approval BEFORE INSERT ON orders "
        "FOR EACH ROW EXECUTE FUNCTION aurelis_check_order_approval()"
    )

    yield (
        "CREATE OR REPLACE FUNCTION aurelis_check_order_size() RETURNS trigger AS $$ "
        "BEGIN IF EXISTS (SELECT 1 FROM trade_approvals ap WHERE ap.ref = "
        "NEW.approval_ref AND CAST(NEW.quantity AS NUMERIC) * "
        "CAST(NEW.expected_price AS NUMERIC) > CAST(ap.final_target AS NUMERIC)) "
        "THEN RAISE EXCEPTION 'Aurelis: an order may not exceed the notional Risk "
        "approved'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    yield "DROP TRIGGER IF EXISTS aurelis_order_may_not_exceed_approval ON orders"
    yield (
        "CREATE TRIGGER aurelis_order_may_not_exceed_approval BEFORE INSERT ON orders "
        "FOR EACH ROW EXECUTE FUNCTION aurelis_check_order_size()"
    )


def install_trading_invariants(connection: sa.Connection) -> tuple[str, ...]:
    """Install the execution triggers. Idempotent."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no execution invariants written for dialect {dialect!r}. Aurelis "
            "will not execute orders without them: an order that reached a "
            "broker without an approval is the one failure this layer exists "
            "to make impossible."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return expected_trading_trigger_names()


def verify_trading_invariants(connection: sa.Connection) -> tuple[str, ...]:
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
        name for name in expected_trading_trigger_names() if name not in installed
    )
