"""The scheduler, and the CLI that proves M0."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from aurelis.cli.demo import run_demo
from aurelis.cli.doctor import Status, run_checks
from aurelis.cli.main import app
from aurelis.core.enums import TaskStatus
from aurelis.runtime import Runtime

runner = CliRunner()


# ----------------------------------------------------------------- scheduler


def test_registering_a_job_makes_it_due(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.scheduler.register(
            session, name="desk.briefing", task_kind="intel.briefing", interval_seconds=3600
        )
        assert len(runtime.scheduler.due(session)) == 1


def test_tick_enqueues_a_task(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.scheduler.register(
            session, name="desk.briefing", task_kind="intel.briefing", interval_seconds=3600
        )
        fired = runtime.scheduler.tick(session)
        assert len(fired) == 1
        assert fired[0].kind == "intel.briefing"
        assert fired[0].status == TaskStatus.QUEUED


def test_a_job_does_not_fire_twice_in_one_interval(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.scheduler.register(
            session, name="j", task_kind="k", interval_seconds=3600
        )
        assert len(runtime.scheduler.tick(session)) == 1
        assert runtime.scheduler.tick(session) == []


def test_missed_firings_do_not_stack(runtime: Runtime) -> None:
    """Six hours asleep should produce one briefing, not six."""
    with runtime.database.session() as session:
        runtime.scheduler.register(session, name="j", task_kind="k", interval_seconds=3600)
        runtime.scheduler.tick(session)

    runtime.clock.advance(hours=6)  # type: ignore[attr-defined]
    with runtime.database.session() as session:
        fired = runtime.scheduler.tick(session)
        assert len(fired) == 1
        skipped = runtime.ledger.for_subject(session, "j")[-1].payload["skipped_firings"]
        assert skipped == 5


def test_reregistering_keeps_the_schedule(runtime: Runtime) -> None:
    """A restart must not delay the whole company by one interval."""
    with runtime.database.session() as session:
        first = runtime.scheduler.register(
            session, name="j", task_kind="k", interval_seconds=3600
        )
        runtime.scheduler.tick(session)
        due_after_fire = first.next_due_at
        again = runtime.scheduler.register(
            session, name="j", task_kind="k", interval_seconds=3600
        )
    assert again.next_due_at == due_after_fire


def test_changing_the_interval_reschedules(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.scheduler.register(session, name="j", task_kind="k", interval_seconds=3600)
        runtime.scheduler.tick(session)
        changed = runtime.scheduler.register(
            session, name="j", task_kind="k", interval_seconds=60
        )
    assert changed.next_due_at == runtime.clock.now()


def test_disabled_jobs_do_not_fire(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.scheduler.register(
            session, name="j", task_kind="k", interval_seconds=60, enabled=False
        )
        assert runtime.scheduler.tick(session) == []


# -------------------------------------------------------------------- doctor


def test_doctor_reports_a_healthy_workspace(runtime: Runtime) -> None:
    checks = run_checks(runtime)
    problems = [c for c in checks if c.status is Status.PROBLEM]
    assert not problems, [f"{c.name}: {c.detail}" for c in problems]


def test_doctor_flags_an_uninitialised_workspace(uninitialised: Runtime) -> None:
    checks = run_checks(uninitialised)
    schema = next(c for c in checks if c.name == "schema")
    assert schema.status is Status.PROBLEM
    assert "aurelis db init" in schema.detail


def test_doctor_flags_dropped_triggers(runtime: Runtime) -> None:
    """A database whose protection was removed must not report healthy."""
    import sqlalchemy as sa

    with runtime.database.engine.begin() as connection:
        connection.execute(sa.text("DROP TRIGGER aurelis_events_no_update"))

    checks = run_checks(runtime)
    triggers = next(c for c in checks if c.name == "append-only triggers")
    assert triggers.status is Status.PROBLEM
    assert "MISSING" in triggers.detail


def test_doctor_reports_absent_engines_as_information_not_failure(runtime: Runtime) -> None:
    """martex-quant is not needed until M4; its absence is a fact, not a fault."""
    checks = run_checks(runtime)
    engine = next(c for c in checks if c.group == "engines")
    assert engine.status in (Status.OK, Status.INFO)


# ---------------------------------------------------------------------- demo


def test_demo_runs_end_to_end(runtime: Runtime) -> None:
    result = run_demo(runtime, rounds=2)
    assert result.chain_ok, result.chain_detail
    assert result.tasks == 4
    assert result.artifacts > 0


def test_demo_second_round_is_entirely_cached(runtime: Runtime) -> None:
    """The most important cost property in the system, asserted rather than hoped."""
    result = run_demo(runtime, rounds=2)
    assert result.model_calls == 4
    assert result.cache_hits == 2


def test_demo_costs_nothing_under_the_mock_provider(runtime: Runtime) -> None:
    assert run_demo(runtime, rounds=2).free


def test_demo_records_token_usage_even_when_free(runtime: Runtime) -> None:
    """Tokens are the scarce resource under a subscription."""
    assert run_demo(runtime, rounds=1).tokens > 0


def test_demo_leaves_a_verifiable_chain(runtime: Runtime) -> None:
    run_demo(runtime, rounds=2)
    with runtime.database.session() as session:
        assert runtime.ledger.verify(session).ok


# ----------------------------------------------------------------------- cli


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "aurelis" in result.stdout


def test_db_init_then_doctor_is_clean(tmp_path: Path) -> None:
    init = runner.invoke(app, ["db", "init", "-w", str(tmp_path)])
    assert init.exit_code == 0, init.stdout

    check = runner.invoke(app, ["doctor", "-w", str(tmp_path)])
    assert check.exit_code == 0, check.stdout
    assert "Healthy" in check.stdout


def test_db_init_is_idempotent(tmp_path: Path) -> None:
    assert runner.invoke(app, ["db", "init", "-w", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["db", "init", "-w", str(tmp_path)]).exit_code == 0


def test_doctor_exits_nonzero_on_an_empty_workspace(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "-w", str(tmp_path)])
    assert result.exit_code == 1


def test_ledger_verify_passes_after_init(tmp_path: Path) -> None:
    runner.invoke(app, ["db", "init", "-w", str(tmp_path)])
    result = runner.invoke(app, ["ledger", "verify", "-w", str(tmp_path)])
    assert result.exit_code == 0
    assert "chain verified" in result.stdout


def test_ledger_verify_is_honest_about_what_it_proves(tmp_path: Path) -> None:
    """Tamper-evident, not tamper-proof. Overstating it would be the exact
    kind of unearned claim this project exists to avoid."""
    runner.invoke(app, ["db", "init", "-w", str(tmp_path)])
    result = runner.invoke(app, ["ledger", "verify", "-w", str(tmp_path)])
    assert "not tamper-proof" in result.stdout


def test_cli_demo_reports_acceptance(tmp_path: Path) -> None:
    result = runner.invoke(app, ["demo", "-w", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "M0 acceptance" in result.stdout


def test_ledger_tail_renders(tmp_path: Path) -> None:
    runner.invoke(app, ["demo", "-w", str(tmp_path)])
    result = runner.invoke(app, ["ledger", "tail", "-w", str(tmp_path), "-n", "5"])
    assert result.exit_code == 0
    assert "seq" in result.stdout
