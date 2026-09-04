"""The agent runtime: hiring, permissions, tools, and one real turn.

The acceptance criteria for M1 live here. The permission tests deliberately go
around the runtime and write raw SQL, because an authority model that only the
application enforces is a diagram.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aurelis.agents.guards import expected_guard_names, verify_guards
from aurelis.agents.roster import StaffedAgent
from aurelis.agents.tables import Agent, AgentState, ToolCall
from aurelis.agents.views import ViewContext, build_view
from aurelis.comms.tables import Message, MessageKind
from aurelis.core.enums import BudgetScope, EventKind, TaskStatus
from aurelis.core.errors import IntegrityViolation, PermissionDenied
from aurelis.intel.briefing import TASK_KIND
from aurelis.intel.tables import MarketObservation
from aurelis.org import Department, ReadView, Seniority, ToolScope, WriteScope
from aurelis.org.desks import Desk
from aurelis.platform.budget.ledger import Spend
from aurelis.runtime import Runtime


@pytest.fixture
def staffed(runtime: Runtime) -> Runtime:
    """A company with its launch roster hired and onboarded."""
    runtime.staff()
    return runtime


def _analyst(runtime: Runtime) -> StaffedAgent:
    with runtime.database.session() as session:
        return runtime.roster.by_handle(session, "INTEL")


# ----------------------------------------------------------------- staffing


def test_launch_roster_is_hired(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        everyone = staffed.roster.all(session)
    assert len(everyone) == 17
    assert {a.handle for a in everyone} >= {"CEO", "INTEL", "RISK", "AUDIT", "GOV"}


def test_every_charter_is_owned_after_staffing(staffed: Runtime) -> None:
    from aurelis.org import CHARTERS

    with staffed.database.session() as session:
        held = [cid for agent in staffed.roster.all(session) for cid in agent.coverage]
    assert sorted(held) == sorted(CHARTERS)


def test_staffing_is_idempotent(staffed: Runtime) -> None:
    staffed.staff()
    with staffed.database.session() as session:
        assert len(staffed.roster.all(session)) == 17


def test_agents_become_active_after_onboarding(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        assert all(a.state is AgentState.ACTIVE for a in staffed.roster.all(session))


def test_hiring_is_recorded_with_who_authorised_it(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        events = staffed.ledger.for_subject(session, analyst.ref)
    hired = [e for e in events if e.kind == EventKind.AGENT_HIRED.value]
    assert len(hired) == 1
    assert hired[0].payload["stands_in_for"] == 9


def test_a_charter_cannot_have_two_owners(staffed: Runtime) -> None:
    """Transferring a charter is a fission, not a second hire."""
    with staffed.database.session() as session:  # noqa: SIM117
        with pytest.raises(IntegrityViolation, match="held by"):
            staffed.roster.hire(
                session,
                handle="INTEL-2",
                department=Department.MARKET_INTELLIGENCE,
                coverage=("intel.technical_analyst",),
                seniority=Seniority.SENIOR,
                desk=Desk.CRYPTO,
            )


def test_handles_are_unique(staffed: Runtime) -> None:
    with staffed.database.session() as session:  # noqa: SIM117
        with pytest.raises(IntegrityViolation, match="already used"):
            staffed.roster.hire(
                session,
                handle="INTEL",
                department=Department.QUANTITATIVE_RESEARCH,
                coverage=("research.engineer",),
                seniority=Seniority.SENIOR,
            )


# --------------------------------------------------- write scope, raw SQL


def test_write_scope_guards_are_installed(staffed: Runtime) -> None:
    from aurelis.agents.guards import SCOPE_GUARDS

    with staffed.database.engine.connect() as connection:
        assert verify_guards(connection) == ()
    assert len(expected_guard_names()) == len(SCOPE_GUARDS)


def test_every_guard_names_a_table_that_exists(staffed: Runtime) -> None:
    """A guard on a missing table is a security guarantee that is really an
    OperationalError at startup."""
    from aurelis.agents.guards import SCOPE_GUARDS

    present = set(sa.inspect(staffed.database.engine).get_table_names())
    assert {g.table for g in SCOPE_GUARDS} <= present


def test_an_agent_without_the_scope_cannot_write_through_raw_sql(staffed: Runtime) -> None:
    """The acceptance criterion. Around the runtime entirely.

    ENG-R holds only research.engineer, which does not grant
    MARKET_OBSERVATION. The database must refuse the row.
    """
    with staffed.database.session() as session:
        engineer = staffed.roster.by_handle(session, "ENG-R")
    assert WriteScope.MARKET_OBSERVATION not in engineer.authority.write_scopes

    with pytest.raises(Exception, match="may not write market_observation"), \
            staffed.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO market_observations "
                "(observation_id, ref, author, desk, symbol, kind, statement, "
                " measures, as_of, observed_at, source, created_at) VALUES "
                "(:i, :r, :a, 'crypto', 'BTC/USDT', 'price_structure', 'smuggled', "
                " '{}', '2026-01-01 00:00:00', '2026-01-02 00:00:00', 'fixture', "
                " '2026-01-02 00:00:00')"
            ),
            {"i": "0" * 32, "r": "OBS-9999", "a": engineer.ref},
        )


def test_an_agent_with_the_scope_may_write_through_raw_sql(staffed: Runtime) -> None:
    """The guard permits what it should. Otherwise the test above proves nothing."""
    analyst = _analyst(staffed)
    assert WriteScope.MARKET_OBSERVATION in analyst.authority.write_scopes

    with staffed.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO market_observations "
                "(observation_id, ref, author, desk, symbol, kind, statement, "
                " measures, as_of, observed_at, source, created_at) VALUES "
                "(:i, :r, :a, 'crypto', 'BTC/USDT', 'price_structure', 'permitted', "
                " '{}', '2026-01-01 00:00:00', '2026-01-02 00:00:00', 'fixture', "
                " '2026-01-02 00:00:00')"
            ),
            {"i": "1" * 32, "r": "OBS-9998", "a": analyst.ref},
        )


def test_an_unknown_agent_cannot_write_at_all(staffed: Runtime) -> None:
    with pytest.raises(Exception, match="may not write market_observation"), \
            staffed.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO market_observations "
                "(observation_id, ref, author, desk, symbol, kind, statement, "
                " measures, as_of, observed_at, source, created_at) VALUES "
                "(:i, :r, 'AG-9999', 'crypto', 'BTC/USDT', 'price_structure', 'ghost', "
                " '{}', '2026-01-01 00:00:00', '2026-01-02 00:00:00', 'fixture', "
                " '2026-01-02 00:00:00')"
            ),
            {"i": "2" * 32, "r": "OBS-9997"},
        )


def test_losing_a_charter_loses_the_authority(staffed: Runtime) -> None:
    """Fission moves coverage, and write scope moves with it atomically."""
    analyst = _analyst(staffed)
    with staffed.database.engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM agent_coverage WHERE agent_ref = :a"), {"a": analyst.ref}
        )

    with pytest.raises(Exception, match="may not write market_observation"), \
            staffed.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO market_observations "
                "(observation_id, ref, author, desk, symbol, kind, statement, "
                " measures, as_of, observed_at, source, created_at) VALUES "
                "(:i, :r, :a, 'crypto', 'BTC/USDT', 'price_structure', 'stale', "
                " '{}', '2026-01-01 00:00:00', '2026-01-02 00:00:00', 'fixture', "
                " '2026-01-02 00:00:00')"
            ),
            {"i": "3" * 32, "r": "OBS-9996", "a": analyst.ref},
        )


def test_observations_cannot_be_learned_before_they_happened(staffed: Runtime) -> None:
    """Collapsing as_of and observed_at is how look-ahead enters."""
    analyst = _analyst(staffed)
    with pytest.raises(Exception, match="ck_observation_not_learned_before_it_happened"), \
            staffed.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO market_observations "
                "(observation_id, ref, author, desk, symbol, kind, statement, "
                " measures, as_of, observed_at, source, created_at) VALUES "
                "(:i, :r, :a, 'crypto', 'BTC/USDT', 'price_structure', 'prescient', "
                " '{}', '2026-06-01 00:00:00', '2026-01-02 00:00:00', 'fixture', "
                " '2026-01-02 00:00:00')"
            ),
            {"i": "4" * 32, "r": "OBS-9995", "a": analyst.ref},
        )


# ---------------------------------------------------------------- read scope


def test_an_agent_cannot_build_a_view_it_was_not_granted(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        engineer = staffed.roster.by_handle(session, "ENG-R")
        assert ReadView.DESK_OBSERVATIONS not in engineer.authority.read_views
        with pytest.raises(PermissionDenied, match="read market.desk_observations"):
            build_view(
                session,
                ReadView.DESK_OBSERVATIONS,
                ViewContext(agent_ref=engineer.ref, desk="crypto"),
                engineer.authority.read_views,
            )


def test_a_granted_view_builds(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        view = build_view(
            session,
            ReadView.DESK_MARKET_SNAPSHOT,
            ViewContext(agent_ref=analyst.ref, desk="crypto"),
            analyst.authority.read_views,
        )
    assert view["source"] == "fixture"
    assert view["is_live"] is False


def test_the_auditor_sees_everything(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        auditor = staffed.roster.by_handle(session, "AUDIT")
        view = build_view(
            session,
            ReadView.DESK_OBSERVATIONS,
            ViewContext(agent_ref=auditor.ref, desk="crypto"),
            auditor.authority.read_views,
        )
    assert "observations" in view


# --------------------------------------------------------------- tool scope


def test_a_tool_the_charters_do_not_grant_is_refused(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        assert ToolScope.BROKER_SUBMIT not in analyst.authority.tools
        with pytest.raises(PermissionDenied, match="use broker.submit"):
            staffed.tools.invoke(
                session,
                agent_ref=analyst.ref,
                scope=ToolScope.BROKER_SUBMIT,
                permitted=analyst.authority.tools,
            )


def test_a_refused_tool_call_is_recorded_before_it_is_raised(staffed: Runtime) -> None:
    """Exactly what an Agent Behavior Auditor samples for."""
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        with pytest.raises(PermissionDenied):
            staffed.tools.invoke(
                session,
                agent_ref=analyst.ref,
                scope=ToolScope.BROKER_SUBMIT,
                permitted=analyst.authority.tools,
            )

    with staffed.database.session() as session:
        call = session.execute(
            sa.select(ToolCall).where(ToolCall.outcome == "refused")
        ).scalars().one()
    assert call.tool == ToolScope.BROKER_SUBMIT.value


def test_tool_calls_are_logged_with_cost(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        staffed.tools.invoke(
            session,
            agent_ref=analyst.ref,
            scope=ToolScope.DATA_OHLCV,
            arguments={"desk": "crypto", "limit": 12},
            permitted=analyst.authority.tools,
        )
        call = session.execute(
            sa.select(ToolCall).where(ToolCall.outcome == "ok")
        ).scalars().one()
    assert call.tool == ToolScope.DATA_OHLCV.value
    assert call.usd == "0"
    assert "bars" in call.detail


def test_data_is_honestly_labelled_as_a_fixture(staffed: Runtime) -> None:
    """Nothing may read as live data that is not live data."""
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        result = staffed.tools.invoke(
            session,
            agent_ref=analyst.ref,
            scope=ToolScope.DATA_OHLCV,
            arguments={"desk": "crypto", "limit": 8},
            permitted=analyst.authority.tools,
        )
    assert result.value["source"] == "fixture"
    assert result.value["is_live"] is False
    assert "not a market simulation" in result.value["caveat"]


# -------------------------------------------------------------------- comms


def test_posting_to_a_channel_an_agent_is_not_in_is_refused(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        engineer = staffed.roster.by_handle(session, "ENG-R")
        with pytest.raises(PermissionDenied, match="post to"):
            staffed.comms.post(
                session,
                from_agent=engineer.ref,
                kind=MessageKind.BRIEFING,
                channel_id="desk-crypto",
                subject="uninvited",
                body="…",
            )


def test_reading_a_channel_an_agent_is_not_in_is_refused(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        engineer = staffed.roster.by_handle(session, "ENG-R")
        with pytest.raises(PermissionDenied, match="read"):
            staffed.comms.read(
                session, channel_id="desk-crypto", agent_ref=engineer.ref
            )


def test_every_message_is_stored_as_an_artifact(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        message = staffed.comms.post(
            session,
            from_agent=analyst.ref,
            kind=MessageKind.OBSERVATION,
            channel_id="desk-crypto",
            subject="a thing",
            body="a body",
        )
        assert message.artifact_digest is not None
        assert staffed.artifacts.exists(message.artifact_digest)


# ------------------------------------------------------------- the real turn


def _queue_briefing(runtime: Runtime, *, tokens: int = 5_000) -> StaffedAgent:
    with runtime.database.session() as session:
        analyst = runtime.roster.by_handle(session, "INTEL")
        runtime.worker.open_daily_budget(session, analyst, tokens=50_000)
        runtime.queue.enqueue(
            session,
            kind=TASK_KIND,
            assignee=analyst.ref,
            subject="desk-crypto",
            payload={"bars": 24},
            allowance=Spend(tokens=tokens),
            envelope=runtime.worker.envelope_for(analyst, at=runtime.clock.now()),
        )
    return analyst


def test_an_agent_completes_a_briefing_turn(staffed: Runtime) -> None:
    analyst = _queue_briefing(staffed)
    with staffed.database.session() as session:
        result = staffed.worker.run_once(session, analyst)
    assert result is not None
    assert result.artifact_digest is not None
    assert "briefed crypto" in result.summary


def test_the_turn_records_an_observation_with_provenance(staffed: Runtime) -> None:
    analyst = _queue_briefing(staffed)
    with staffed.database.session() as session:
        staffed.worker.run_once(session, analyst)
        observation = session.execute(sa.select(MarketObservation)).scalars().one()

    assert observation.author == analyst.ref
    assert observation.source == "fixture"
    assert observation.data_digest, "an observation must name the data it came from"
    assert observation.artifact_digest
    assert observation.observed_at >= observation.as_of


def test_the_turn_posts_a_briefing_citing_its_evidence(staffed: Runtime) -> None:
    analyst = _queue_briefing(staffed)
    with staffed.database.session() as session:
        staffed.worker.run_once(session, analyst)
        message = session.execute(
            sa.select(Message).where(Message.kind == MessageKind.BRIEFING.value)
        ).scalars().one()

    assert message.from_agent == analyst.ref
    assert message.channel_id == "desk-crypto"
    assert len(message.evidence_refs) == 3
    assert message.claims


def test_the_turn_spends_tokens_and_records_them(staffed: Runtime) -> None:
    analyst = _queue_briefing(staffed)
    with staffed.database.session() as session:
        staffed.worker.run_once(session, analyst)
    with staffed.database.session() as session:
        spent = staffed.budget.spent(
            session,
            BudgetScope.AGENT_DAY,
            f"{analyst.ref}:{staffed.clock.now().date().isoformat()}",
        )
    assert spent.tokens > 0
    assert spent.usd == 0  # mock provider


def test_the_chain_still_verifies_after_a_turn(staffed: Runtime) -> None:
    analyst = _queue_briefing(staffed)
    with staffed.database.session() as session:
        staffed.worker.run_once(session, analyst)
        assert staffed.ledger.verify(session).ok


def test_an_exhausted_daily_budget_refuses_the_work_at_dispatch(staffed: Runtime) -> None:
    """The acceptance criterion: budget bites before the work, not after.

    The task never enters the queue at all, so no model is called and no
    observation is written. Refusal is a recorded terminal outcome.
    """
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        staffed.worker.open_daily_budget(session, analyst, tokens=10)
        task = staffed.queue.enqueue(
            session,
            kind=TASK_KIND,
            assignee=analyst.ref,
            payload={"bars": 24},
            allowance=Spend(tokens=5_000),
            envelope=staffed.worker.envelope_for(analyst, at=staffed.clock.now()),
        )

    assert task.status == TaskStatus.REFUSED_BUDGET
    assert analyst.ref in (task.budget_scope_id or "")

    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        assert staffed.worker.run_once(session, analyst) is None
        assert session.execute(sa.select(MarketObservation)).scalars().first() is None
        refused = [
            e
            for e in staffed.ledger.for_subject(session, task.ref)
            if e.kind == EventKind.TASK_REFUSED_BUDGET.value
        ]
    assert refused, "a refusal must be recorded, not silent"


def test_the_loop_re_checks_the_budget_before_working(staffed: Runtime) -> None:
    """The second gate.

    A task queued while the allowance was healthy must still be refused if the
    allowance is gone by the time it is picked up -- otherwise a burst of
    cheaply-queued work could spend past its limit.
    """
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        staffed.worker.open_daily_budget(session, analyst, tokens=50_000)
        task = staffed.queue.enqueue(
            session,
            kind=TASK_KIND,
            assignee=analyst.ref,
            payload={"bars": 24},
            allowance=Spend(tokens=5_000),
            envelope=staffed.worker.envelope_for(analyst, at=staffed.clock.now()),
        )
        assert task.status == TaskStatus.QUEUED

        # Spend the allowance after queueing but before the turn runs.
        staffed.budget.record(
            session,
            staffed.worker.envelope_for(analyst, at=staffed.clock.now()),
            Spend(tokens=49_000),
            actor=analyst.ref,
            reason="something else",
        )

    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        assert staffed.worker.run_once(session, analyst) is None
        assert session.execute(sa.select(MarketObservation)).scalars().first() is None
        exhausted = [
            e
            for e in staffed.ledger.for_subject(session, task.ref)
            if e.kind == EventKind.BUDGET_EXHAUSTED.value
        ]
    assert exhausted, "budget exhaustion at the loop must be recorded, not silent"


def test_a_briefing_that_invents_a_figure_fails_the_turn(staffed: Runtime) -> None:
    """The rule that separates research from articulate opinion.

    A model that states a number it was not given must not have that number
    reach the record. The turn fails and the reason is kept against the agent.
    """
    from aurelis.platform.llm.cache import CachingProvider
    from aurelis.platform.llm.providers import MockProvider

    liar = MockProvider(
        responder=lambda _: "Momentum is clear: the Sharpe ratio over this window was 2.31."
    )
    staffed.worker._provider = CachingProvider(  # noqa: SLF001 - deliberate injection
        liar, staffed.artifacts, ledger=staffed.ledger, clock=staffed.clock, enabled=False
    )

    analyst = _queue_briefing(staffed)
    with staffed.database.session() as session, pytest.raises(ValueError, match="not present"):
        staffed.worker.run_once(session, analyst)

    with staffed.database.session() as session:
        assert session.execute(sa.select(MarketObservation)).scalars().first() is None


def test_an_agent_with_no_task_does_nothing(staffed: Runtime) -> None:
    """Idle is free. A department with no work makes no calls."""
    analyst = _analyst(staffed)
    with staffed.database.session() as session:
        assert staffed.worker.run_once(session, analyst) is None


def test_a_task_with_no_handler_fails_rather_than_hanging(staffed: Runtime) -> None:
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        task = staffed.queue.enqueue(
            session, kind="intel.telepathy", assignee=analyst.ref
        )
        staffed.worker.run_once(session, analyst)
        session.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert "no handler" in (task.failure_reason or "")


def test_an_agent_cannot_edit_its_own_record(staffed: Runtime) -> None:
    """Self-modification would make the growth mechanism unauditable."""
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        row = session.execute(
            sa.select(Agent).where(Agent.ref == analyst.ref)
        ).scalar_one()
    # There is deliberately no API for this; the check is that the Roster
    # exposes no mutation of coverage, tier or budget by the agent itself.
    assert not hasattr(staffed.roster, "grant_charter")
    assert not hasattr(staffed.roster, "set_budget")
    assert row.hired_by == "operator"


def test_second_identical_briefing_is_served_from_cache(staffed: Runtime) -> None:
    """The cost property, at the agent level."""
    analyst = _queue_briefing(staffed)
    with staffed.database.session() as session:
        staffed.worker.run_once(session, analyst)

    with staffed.database.session() as session:
        staffed.queue.enqueue(
            session,
            kind=TASK_KIND,
            assignee=analyst.ref,
            payload={"bars": 24},
            allowance=Spend(tokens=5_000),
            envelope=staffed.worker.envelope_for(analyst, at=staffed.clock.now()),
        )
    with staffed.database.session() as session:
        staffed.worker.run_once(session, analyst)
        stats = staffed.provider.stats(session)
    assert stats.hits == 1


def test_no_module_imports_the_live_broker_adapter() -> None:
    """ADR-0006: live execution is absent, not disabled."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "aurelis"
    offenders = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "mt5" in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == [], f"modules referencing the MT5 adapter: {offenders}"
