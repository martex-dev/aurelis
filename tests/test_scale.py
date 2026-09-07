"""M13 — scale and hardening.

Named after the roadmap's list: multi-worker execution, failure recovery,
backup and restore, chain verification, and the target shape of 80–100+ agents
across seven desks.

Two of these are claims about software rather than about how many people the
company chose to employ, and they are tested as such: that the runtime does not
change as the company grows (ADR-0003), and that two workers never do the same
task twice.
"""

from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from aurelis.agents.tables import Agent, AgentCoverage, AgentState
from aurelis.cli.demo import run_demo
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import BudgetPeriod, BudgetScope, TaskStatus
from aurelis.org.charters import CHARTERS, Seniority
from aurelis.org.desks import DESKS, Desk
from aurelis.org.registry import resolve_authority
from aurelis.org.slots import COMPANY_WIDE, Slot, census, required_slots
from aurelis.orgdev.scaling import run_scaling
from aurelis.orgdev.staffing import staffing_plan, unstaffed_desks
from aurelis.orgdev.states import EffectVerdict
from aurelis.platform.backup import back_up, restore, verify_workspace
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.queue.queue import Spend
from aurelis.runtime import COMPANY_SCOPE_ID, Runtime


@pytest.fixture
def staffed(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


@pytest.fixture
def opened(staffed: Runtime) -> Runtime:
    """A company with all seven desks open, and 78 jobs nobody holds."""
    with staffed.database.session() as session:
        staffed.desks.open_all(session)
    return staffed


# ------------------------------------------------------- coverage has a desk


def test_a_charter_that_differs_per_market_is_held_per_market() -> None:
    """ADR-0004's second dimension, which nothing implemented until M13.

    Thirteen charters are desk-specific. With seven desks that is 91 jobs, not
    13 — and while coverage was flat, opening a desk gave the existing Technical
    Analyst a seventh market rather than giving the desk an analyst.
    """
    desk_specific = [c for c in CHARTERS.values() if c.desk_specific]
    assert len(desk_specific) == 13

    slots = required_slots([d.value for d in DESKS])
    assert len(slots) == 13 * len(DESKS) + (len(CHARTERS) - 13) == 154

    per_desk = {s for s in slots if s.desk == Desk.OPTIONS.value}
    assert len(per_desk) == 13
    assert all(s.charter.desk_specific for s in per_desk)


def test_a_company_wide_charter_is_held_once(opened: Runtime) -> None:
    """One Company Manager. Giving each desk its own would invent work."""
    with opened.database.session() as session:
        taken = census(session)
    manager = Slot("exec.company_manager", COMPANY_WIDE)
    assert manager in taken.required
    assert len(taken.held[manager]) == 1
    assert not any(
        s.charter_id == "exec.company_manager" and s.desk for s in taken.required
    )


def test_a_desk_specific_charter_needs_a_desk() -> None:
    """Defaulting would put every desk-specific charter on one nameless desk,
    and the census would then read as complete."""
    from aurelis.org.slots import desk_for_charter

    assert desk_for_charter("exec.company_manager", None) == COMPANY_WIDE
    assert desk_for_charter("intel.technical_analyst", Desk.FX) == "fx"
    with pytest.raises(ValueError, match="must say which desk"):
        desk_for_charter("intel.technical_analyst", None)


def test_opening_a_desk_creates_jobs_nobody_holds(opened: Runtime) -> None:
    """Which is a countable fact about the org chart, not a reminder."""
    with opened.database.session() as session:
        taken = census(session)
        hits = unstaffed_desks(session)

    assert len(taken.required) == 154
    assert len(taken.unstaffed) == 78
    assert {h.subject for h in hits} == {
        d.value for d in DESKS if d is not Desk.CRYPTO
    }
    assert all(h.reading.value == 13 for h in hits)


def test_the_database_refuses_to_orphan_a_desks_charter(opened: Runtime) -> None:
    """Keyed on the charter alone, handing over the Options analyst would have
    looked satisfied by the FX analyst still holding theirs."""
    with (
        pytest.raises(Exception, match="last agent holding this charter"),
        opened.database.engine.begin() as conn,
    ):
        conn.execute(
            sa.text(
                "DELETE FROM agent_coverage WHERE charter_id = "
                "'intel.technical_analyst' AND desk = 'crypto'"
            )
        )


# ------------------------------------------- acceptance: the desks get staffed


def test_the_company_staffs_its_desks_through_the_org_change_lifecycle(
    opened: Runtime,
) -> None:
    """Not a script that inserts rows.

    Each desk is a measured trigger, a proposal carrying the measurement, a
    prediction hashed before the Board sees it, a decision, and an effect
    measured against the locked prediction.
    """
    outcome = run_scaling(opened)

    assert len(outcome.hirings) == 6
    assert outcome.hired == 30
    assert outcome.agents_after == outcome.agents_before + 30
    assert outcome.unstaffed_before == 78
    assert outcome.unstaffed_after == 0
    assert outcome.coverage_intact

    for hiring in outcome.hirings:
        assert hiring.effect.verdict is EffectVerdict.IMPROVED
        assert hiring.meeting_ref.startswith("MTG-")
        assert hiring.change_ref.startswith("ORG-")
        assert hiring.slots_after == 0

    with opened.database.session() as session:
        taken = census(session)
    assert taken.intact
    assert taken.coverage == "154/154"


def test_a_desk_is_staffed_the_way_the_launch_roster_staffed_crypto(
    opened: Runtime,
) -> None:
    """Five generalists, not thirteen specialists.

    A desk running on fixtures generates no load, and hiring one person per
    charter would be assuming headcount is capability — which M11 measured and
    found false.
    """
    with opened.database.session() as session:
        plan = staffing_plan(session, Desk.OPTIONS)
    assert len(plan) == 5
    assert sum(len(entry.charters) for entry in plan) == 13
    assert {entry.handle for entry in plan} == {
        "INTEL-OPT",
        "QUANT-OPT",
        "STRAT-OPT",
        "RISK-OPT",
        "TRADE-OPT",
    }
    assert all(entry.desk is Desk.OPTIONS for entry in plan)


def test_every_hire_is_scored_before_it_works(opened: Runtime) -> None:
    """A desk hire is a hire: it runs the scenario suite first (ADR-0005)."""
    outcome = run_scaling(opened)
    with opened.database.session() as session:
        for hiring in outcome.hirings:
            for ref in hiring.hired:
                record = opened.onboarding.latest(session, ref)
                assert record is not None, ref
                assert record.verdict == hiring.onboarding[ref]
                agent = session.execute(
                    sa.select(Agent).where(Agent.ref == ref)
                ).scalar_one()
                assert agent.state in {AgentState.ACTIVE, AgentState.RETRAINING}


# ------------------------------------------------------- the scale claim


def test_the_runtime_does_not_change_at_full_specialisation(
    opened: Runtime,
) -> None:
    """ADR-0003's promise, tested at the shape it promised.

    One dedicated agent per slot: 154 agents, every charter held once per desk
    it applies to. This is a claim about the software, not about how many
    people the company chose to employ — the company runs at 47, and the
    machinery is shown to run here.
    """
    # Step one: a dedicated hire for every job nobody holds.
    with opened.database.session() as session:
        wanted = sorted(census(session).unstaffed)
        for index, slot in enumerate(wanted):
            opened.roster.hire(
                session,
                handle=f"SP-{index:04d}",
                department=slot.charter.department,
                coverage=(slot.charter_id,),
                seniority=Seniority.SENIOR,
                desk=Desk(slot.desk) if slot.desk else None,
                hired_by="scale-proof",
            )

    # Step two: split the launch generalists down to one job each, through the
    # company's own fission mechanism rather than by rewriting rows.
    split = 0
    while True:
        with opened.database.session() as session:
            widest = _widest_generalist(session)
            if widest is None:
                break
            ref, slots = widest
            opened.handover.split(
                session,
                from_ref=ref,
                handle=f"FS-{split:04d}",
                charters=(slots[0].charter_id,),
                seniority=Seniority.SENIOR,
                desk=Desk(slots[0].desk) if slots[0].desk else None,
            )
        split += 1
        assert split < 200, "the split loop is not converging"

    with opened.database.session() as session:
        taken = census(session)
        headcount = session.execute(
            sa.select(sa.func.count())
            .select_from(Agent)
            .where(Agent.state != AgentState.RETIRED)
        ).scalar_one()

    assert taken.intact
    assert len(taken.required) == 154
    assert headcount == 154, "one agent per slot is full specialisation"
    assert headcount > 100, "the roadmap's target shape"

    # Authority still resolves, and it resolves per charter rather than per
    # slot: a Technical Analyst has the same scopes on every desk.
    with opened.database.session() as session:
        one = opened.roster.by_handle(session, "SP-0000")
        assert len(one.coverage) == 1
        assert one.authority.write_scopes or one.authority.read_views
        assert resolve_authority(one.coverage).tier == one.authority.tier


def _widest_generalist(session: sa.orm.Session) -> tuple[str, list[Slot]] | None:
    """The working agent holding the most slots, if it holds more than one."""
    held: dict[str, list[Slot]] = {}
    rows = session.execute(
        sa.select(AgentCoverage.agent_ref, AgentCoverage.charter_id, AgentCoverage.desk)
        .join(Agent, Agent.ref == AgentCoverage.agent_ref)
        .where(Agent.state != AgentState.RETIRED)
    ).all()
    for agent_ref, charter_id, desk in rows:
        held.setdefault(str(agent_ref), []).append(Slot(str(charter_id), str(desk)))
    widest = max(held.items(), key=lambda kv: (len(kv[1]), kv[0]), default=None)
    if widest is None or len(widest[1]) < 2:
        return None
    return widest[0], sorted(widest[1])


def test_the_write_scope_guards_still_refuse_at_scale(opened: Runtime) -> None:
    """Growth must not dilute separation of duty."""
    with opened.database.session() as session:
        analyst = opened.roster.hire(
            session,
            handle="SP-INTEL-FX",
            department=CHARTERS["intel.technical_analyst"].department,
            coverage=("intel.technical_analyst",),
            seniority=Seniority.SENIOR,
            desk=Desk.FX,
        )
        ref = analyst.ref

    # A Technical Analyst may write a market observation on its own desk...
    with opened.database.engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO market_observations (observation_id, ref, author, "
                "desk, symbol, kind, statement, measures, as_of, observed_at, "
                "source, created_at) VALUES (:i, 'OBS-9990', :a, 'fx', "
                "'EURUSD', 'price_structure', 'a note', '{}', "
                "'2026-01-01 00:00:00', '2026-01-02 00:00:00', 'fixture', "
                "'2026-01-02 00:00:00')"
            ),
            {"i": b"\x01" * 16, "a": ref},
        )

    # ...and a research specialist on the same desk may not, at 100+ agents
    # exactly as at 17. Growth must not dilute separation of duty.
    with opened.database.session() as session:
        quant = opened.roster.hire(
            session,
            handle="SP-QUANT-FX",
            department=CHARTERS["research.backtest"].department,
            coverage=("research.backtest",),
            seniority=Seniority.SENIOR,
            desk=Desk.FX,
        )
        quant_ref = quant.ref

    with (
        pytest.raises(Exception, match="may not write market_observation"),
        opened.database.engine.begin() as conn,
    ):
        conn.execute(
            sa.text(
                "INSERT INTO market_observations (observation_id, ref, author, "
                "desk, symbol, kind, statement, measures, as_of, observed_at, "
                "source, created_at) VALUES (:i, 'OBS-9991', :a, 'fx', "
                "'EURUSD', 'price_structure', 'smuggled', '{}', "
                "'2026-01-01 00:00:00', '2026-01-02 00:00:00', 'fixture', "
                "'2026-01-02 00:00:00')"
            ),
            {"i": b"\x02" * 16, "a": quant_ref},
        )


# ----------------------------------------------------------- concurrency


def test_two_workers_never_claim_the_same_task(staffed: Runtime) -> None:
    """This failed before M13, silently.

    The claim selected a candidate and then wrote CLAIMED onto it. SQLAlchemy
    opens a DEFERRED transaction on SQLite so the SELECT takes no lock: eight
    workers against forty tasks produced fifty-three claims and no error at
    all — thirteen tasks done twice, each with its own budget draw. The write
    is a compare-and-set now.
    """
    tasks, workers = 40, 8
    with staffed.database.session() as session:
        staffed.budget.open(
            session,
            scope=BudgetScope.COMPANY,
            scope_id=COMPANY_SCOPE_ID,
            usd=Decimal("40"),
            tokens=40_000_000,
            period=BudgetPeriod.LIFETIME,
        )
        for i in range(tasks):
            staffed.queue.enqueue(
                session,
                kind="stress.unit",
                subject=f"job-{i}",
                allowance=Spend(Decimal("0.001"), 100),
            )

    claimed: list[str] = []
    failures: list[str] = []
    lock = threading.Lock()
    gate = threading.Barrier(workers)

    def work(name: str) -> None:
        gate.wait()
        while True:
            try:
                with staffed.database.session() as session:
                    task = staffed.queue.claim(
                        session, worker=name, kinds=("stress.unit",)
                    )
                    if task is None:
                        return
                    ref = task.ref
                with lock:
                    claimed.append(ref)
            except Exception as exc:  # noqa: BLE001 - the point of the test
                with lock:
                    failures.append(f"{name}: {exc}")
                return

    threads = [threading.Thread(target=work, args=(f"W{i}",)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not failures, failures
    assert len(claimed) == len(set(claimed)), "a task was claimed twice"
    assert len(claimed) == tasks

    with staffed.database.session() as session:
        still_queued = session.execute(
            sa.select(sa.func.count())
            .select_from(sa.table("tasks", sa.column("status")))
            .where(sa.column("status") == TaskStatus.QUEUED)
        ).scalar_one()
    assert still_queued == 0


def test_a_claim_that_loses_the_race_returns_the_next_task(
    staffed: Runtime,
) -> None:
    """A worker that loses a compare-and-set moves on rather than failing."""
    with staffed.database.session() as session:
        staffed.budget.open(
            session,
            scope=BudgetScope.COMPANY,
            scope_id=COMPANY_SCOPE_ID,
            usd=Decimal("1"),
            tokens=100_000,
            period=BudgetPeriod.LIFETIME,
        )
        for i in range(2):
            staffed.queue.enqueue(
                session,
                kind="race.unit",
                subject=f"job-{i}",
                allowance=Spend(Decimal("0.001"), 100),
            )

    with staffed.database.session() as session:
        first = staffed.queue.claim(session, worker="A", kinds=("race.unit",))
        second = staffed.queue.claim(session, worker="B", kinds=("race.unit",))
        third = staffed.queue.claim(session, worker="C", kinds=("race.unit",))
    assert first is not None and second is not None
    assert first.ref != second.ref
    assert third is None


# -------------------------------------------------------- backup and restore


def _workspace(tmp_path: Path, name: str) -> Settings:
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    return Settings(
        home=home,
        provider="mock",
        cache_models=True,
        strict_integrity=True,
        company_budget_usd="10",
        company_budget_tokens=1_000_000,
    )


def test_a_backup_round_trips_and_is_verified_not_assumed(
    tmp_path: Path,
) -> None:
    """A restore that produces a database which opens is not a restore."""
    settings = _workspace(tmp_path, "live")
    live = Runtime.build(
        settings,
        clock=FrozenClock(dt.datetime(2026, 9, 7, 9, 0, tzinfo=dt.UTC)),
        provider=MockProvider(),
    )
    live.initialise()
    live.staff()
    run_demo(live)
    live.close()

    report = back_up(settings, tmp_path / "backup")
    assert report.events > 0
    assert report.head

    restored = restore(tmp_path / "backup", _workspace(tmp_path, "restored"))
    assert restored.ok, restored.describe()
    assert restored.events == report.events
    assert restored.head == report.head
    assert restored.chain_ok and restored.artifacts_ok


def test_a_restore_refuses_a_tampered_artifact(tmp_path: Path) -> None:
    """The store is content-addressed, so corruption is caught by rehashing."""
    settings = _workspace(tmp_path, "live")
    live = Runtime.build(
        settings,
        clock=FrozenClock(dt.datetime(2026, 9, 7, 9, 0, tzinfo=dt.UTC)),
        provider=MockProvider(),
    )
    live.initialise()
    live.staff()
    # The demonstration is what writes artifacts; staffing alone writes none,
    # and a backup test with nothing to check would pass on an empty store.
    run_demo(live)
    live.close()

    back_up(settings, tmp_path / "backup")
    target = _workspace(tmp_path, "restored")
    assert restore(tmp_path / "backup", target).ok

    blobs = [p for p in target.object_store.rglob("*") if p.is_file()]
    assert blobs, "the demonstration wrote no artifacts to check"
    blobs[0].write_bytes(b"tampered")

    checked = verify_workspace(target)
    assert not checked.ok
    assert not checked.artifacts_ok
    assert checked.chain_ok, "the chain is intact; it is the blob that moved"
    assert any("no longer hash to their name" in p for p in checked.problems)


def test_a_backup_with_no_manifest_is_refused(tmp_path: Path) -> None:
    """Without the expected event count, a restore can only report that a file
    opened — not that it is the right file."""
    settings = _workspace(tmp_path, "live")
    live = Runtime.build(
        settings,
        clock=FrozenClock(dt.datetime(2026, 9, 7, 9, 0, tzinfo=dt.UTC)),
        provider=MockProvider(),
    )
    live.initialise()
    live.close()

    destination = tmp_path / "backup"
    back_up(settings, destination)
    (destination / "aurelis-backup.json").unlink()

    report = restore(destination, _workspace(tmp_path, "restored"))
    assert not report.ok
    assert any("aurelis-backup.json" in p for p in report.problems)
