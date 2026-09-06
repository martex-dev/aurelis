"""Write scope, enforced by the database.

The separation of duty this company rests on — a researcher cannot write a risk
assessment, only the Registrar locks a preregistration, only one charter
reaches a broker — is worth nothing if it lives in application code. Any new
code path, any migration, any SQL console gets around it.

So the charters are mirrored into tables (:mod:`aurelis.org.tables`) and every
scope-guarded table carries a ``BEFORE INSERT`` trigger that checks the author
actually holds the scope, through some charter it covers:

.. code-block:: sql

    WHEN NOT EXISTS (
        SELECT 1 FROM agent_coverage ac
        JOIN charter_write_scopes cw ON cw.charter_id = ac.charter_id
        WHERE ac.agent_ref = NEW.author AND cw.scope = 'market_observation'
    )
    BEGIN SELECT RAISE(ABORT, '...'); END

An agent that loses a charter loses the authority in the same transaction. A
fission moves coverage, and the write scope moves with it atomically. And a
row inserted by hand, with the runtime bypassed entirely, is refused by the
database — which is the standard a company record has to meet.

This lives in ``agents/`` rather than ``platform/`` on purpose: the platform
must not know what a charter is.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import sqlalchemy as sa

from aurelis.org.scopes import WriteScope

__all__ = ["SCOPE_GUARDS", "ScopeGuard", "expected_guard_names", "install_guards", "verify_guards"]


@dataclass(frozen=True, slots=True)
class ScopeGuard:
    """One table whose inserts require a write scope."""

    table: str
    author_column: str
    scope: WriteScope

    @property
    def trigger_name(self) -> str:
        return f"aurelis_{self.table}_write_scope"


SCOPE_GUARDS: tuple[ScopeGuard, ...] = (
    ScopeGuard("market_observations", "author", WriteScope.MARKET_OBSERVATION),
    ScopeGuard("messages", "from_agent", WriteScope.MESSAGE),
    ScopeGuard("meeting_turns", "speaker", WriteScope.MEETING_TURN),
    ScopeGuard("meeting_objections", "author", WriteScope.OBJECTION),
    ScopeGuard("forecasts", "agent_ref", WriteScope.FORECAST),
    # Strategy content. Components share the strategy-version scope: a
    # component *is* strategy specification, and the roles that may write one
    # are the roles that may write the other.
    ScopeGuard("components", "author", WriteScope.STRATEGY_VERSION),
    ScopeGuard("strategy_versions", "created_by", WriteScope.STRATEGY_VERSION),
    ScopeGuard("promotion_gates", "registered_by", WriteScope.PROMOTION_GATE),
    ScopeGuard("allocations", "decided_by", WriteScope.PORTFOLIO_ALLOCATION),
    # The execution chain. Each link is a different role on purpose: the agent
    # that wants the exposure is not the one that permits it, and neither is
    # the one that sends the order.
    ScopeGuard("trade_proposals", "proposed_by", WriteScope.TRADE_PROPOSAL),
    ScopeGuard("risk_assessments", "assessor", WriteScope.RISK_ASSESSMENT),
    ScopeGuard("trade_approvals", "approved_by", WriteScope.TRADE_APPROVAL),
    ScopeGuard("orders", "submitted_by", WriteScope.ORDER),
    ScopeGuard("alerts", "raised_by", WriteScope.ALERT),
)
"""Guarded tables, and the separation of duties they make real.

Each entry means: inserting into this table requires the author named in that
column to hold this scope through a charter they cover. The trading rows are
the ones that matter most — ``trade_proposals``, ``risk_assessments``,
``trade_approvals`` and ``orders`` are four different scopes held by four
different roles, so "the agent that wants the exposure is not the agent that
approves it" is enforced by the database rather than by everyone remembering.
"""


def expected_guard_names() -> tuple[str, ...]:
    return tuple(sorted(g.trigger_name for g in SCOPE_GUARDS))


def _condition(guard: ScopeGuard) -> str:
    return (
        "NOT EXISTS ("
        "SELECT 1 FROM agent_coverage ac "
        "JOIN charter_write_scopes cw ON cw.charter_id = ac.charter_id "
        f"WHERE ac.agent_ref = NEW.{guard.author_column} "
        f"AND cw.scope = '{guard.scope.value}')"
    )


def _message(guard: ScopeGuard) -> str:
    return (
        f"Aurelis: agent may not write {guard.scope.value} "
        "-- no charter it covers grants that scope"
    )


def _sqlite_statements() -> Iterator[str]:
    for guard in SCOPE_GUARDS:
        yield (
            f"CREATE TRIGGER IF NOT EXISTS {guard.trigger_name} "
            f"BEFORE INSERT ON {guard.table} FOR EACH ROW "
            f"WHEN {_condition(guard)} "
            f"BEGIN SELECT RAISE(ABORT, '{_message(guard)}'); END"
        )


def _postgres_statements() -> Iterator[str]:
    yield (
        "CREATE OR REPLACE FUNCTION aurelis_require_write_scope() RETURNS trigger AS $$ "
        "DECLARE author_ref text; permitted boolean; BEGIN "
        "EXECUTE format('SELECT ($1).%I', TG_ARGV[1]) INTO author_ref USING NEW; "
        "SELECT EXISTS (SELECT 1 FROM agent_coverage ac "
        "JOIN charter_write_scopes cw ON cw.charter_id = ac.charter_id "
        "WHERE ac.agent_ref = author_ref AND cw.scope = TG_ARGV[0]) INTO permitted; "
        "IF NOT permitted THEN RAISE EXCEPTION "
        "'Aurelis: agent %% may not write %% -- no charter it covers grants that scope', "
        "author_ref, TG_ARGV[0]; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    for guard in SCOPE_GUARDS:
        yield f"DROP TRIGGER IF EXISTS {guard.trigger_name} ON {guard.table}"
        yield (
            f"CREATE TRIGGER {guard.trigger_name} BEFORE INSERT ON {guard.table} "
            "FOR EACH ROW EXECUTE FUNCTION aurelis_require_write_scope("
            f"'{guard.scope.value}', '{guard.author_column}')"
        )


def install_guards(connection: sa.Connection) -> tuple[str, ...]:
    """Install the write-scope triggers. Idempotent."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statements = list(_sqlite_statements())
    elif dialect == "postgresql":
        statements = list(_postgres_statements())
    else:
        raise NotImplementedError(
            f"no write-scope guards written for dialect {dialect!r}. Aurelis "
            "will not run without them: separation of duty is a guarantee, not "
            "a best effort."
        )
    for statement in statements:
        connection.execute(sa.text(statement))
    return expected_guard_names()


def verify_guards(connection: sa.Connection) -> tuple[str, ...]:
    """Return the expected guards that are **missing**. Empty means protected."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        )
    elif dialect == "postgresql":
        rows = connection.execute(sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))
    else:  # pragma: no cover - guarded by install_guards
        raise NotImplementedError(dialect)
    installed = {str(row[0]) for row in rows}
    return tuple(name for name in expected_guard_names() if name not in installed)
