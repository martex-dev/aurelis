"""The append-only triggers, tested against raw SQL.

This is the point of the whole exercise. Every assertion here goes through a
raw connection rather than the ORM, because an invariant that only Aurelis's
own code enforces is a convention, and the company's record has to be
auditable by someone who does not trust the code that wrote it.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aurelis.core.enums import EventKind
from aurelis.platform.budget.ledger import BudgetEnvelope, Spend
from aurelis.platform.db.tables import APPEND_ONLY_TABLES
from aurelis.platform.db.triggers import expected_trigger_names, verify_invariants
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef
from aurelis.runtime import COMPANY_SCOPE_ID, Runtime


@pytest.fixture
def seeded(runtime: Runtime) -> Runtime:
    """One row in every protected table.

    Without this the tests below would pass vacuously: an UPDATE that matches
    no rows never fires a row-level trigger, so an empty table looks protected
    whether it is or not.
    """
    with runtime.database.session() as session:
        runtime.ledger.append(session, kind=EventKind.DEMO_EXCHANGE, payload={"seed": True})
        runtime.artifacts.put(session, b"seed artifact", kind="seed")
        runtime.budget.record(
            session,
            BudgetEnvelope(company=COMPANY_SCOPE_ID),
            Spend(tokens=1),
            reason="seed",
        )
        runtime.provider.complete(
            session,
            LlmRequest(
                model=ModelRef(provider="mock", model="mock-1"),
                system="seed",
                messages=(Message("user", "seed"),),
            ),
        )
    return runtime


def test_every_expected_trigger_is_installed(runtime: Runtime) -> None:
    with runtime.database.engine.connect() as connection:
        assert verify_invariants(connection) == ()


def test_trigger_count_matches_the_protected_tables(runtime: Runtime) -> None:
    assert len(expected_trigger_names()) == len(APPEND_ONLY_TABLES) * 2


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_update_is_refused_by_raw_sql(seeded: Runtime, table: str) -> None:
    with pytest.raises(Exception, match="append-only"), seeded.database.engine.begin() as conn:
        conn.execute(sa.text(f"UPDATE {table} SET created_at = created_at"))


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_delete_is_refused_by_raw_sql(seeded: Runtime, table: str) -> None:
    with pytest.raises(Exception, match="append-only"), seeded.database.engine.begin() as conn:
        conn.execute(sa.text(f"DELETE FROM {table}"))


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_the_seed_fixture_actually_populated_each_table(seeded: Runtime, table: str) -> None:
    """Guards the tests above from passing vacuously on an empty table."""
    with seeded.database.engine.connect() as conn:
        count = conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
    assert count > 0


def test_mutable_tables_are_still_mutable(runtime: Runtime) -> None:
    """Tasks and budgets must remain updatable — they are state, not history."""
    with runtime.database.engine.begin() as conn:
        conn.execute(sa.text("UPDATE tasks SET priority = priority"))
        conn.execute(sa.text("UPDATE budgets SET limit_tokens = limit_tokens"))


def test_foreign_keys_are_enforced_on_sqlite(runtime: Runtime) -> None:
    """SQLite ignores foreign keys unless asked, per connection.

    Several of the company's rules — an approval requires an assessment, an
    order requires an approval — will be foreign keys. Without the pragma they
    would be documentation.
    """
    with runtime.database.engine.connect() as connection:
        enabled = connection.execute(sa.text("PRAGMA foreign_keys")).scalar_one()
    assert enabled == 1


def test_reinstalling_invariants_is_idempotent(runtime: Runtime) -> None:
    runtime.database.create_all()
    runtime.database.create_all()
    with runtime.database.engine.connect() as connection:
        assert verify_invariants(connection) == ()


def test_missing_triggers_are_reported_not_hidden(runtime: Runtime) -> None:
    with runtime.database.engine.begin() as connection:
        connection.execute(sa.text("DROP TRIGGER aurelis_events_no_delete"))
    with runtime.database.engine.connect() as connection:
        missing = verify_invariants(connection)
    assert missing == ("aurelis_events_no_delete",)
