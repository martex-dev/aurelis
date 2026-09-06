"""M11 — org development: the company grows itself.

Named after the acceptance criteria in ``docs/07-roadmap.md``:

* the company proposes, decides, applies and **measures** a structural change
  to itself, and the result is recorded whichever way it comes out,
* total charter coverage is preserved across every fission and fusion,
* no charter area is ever orphaned.

Plus the properties those rest on: that a prediction cannot be re-aimed after
the outcome, that an unmeasurable reading never fires a trigger, and that an
agent may not propose a change to its own record.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.agents.tables import Agent, AgentCoverage, AgentState
from aurelis.org.charters import CHARTERS, Seniority
from aurelis.org.departments import Department
from aurelis.orgdev.demonstration import (
    FIRST_SPLIT,
    SECOND_SPLIT,
    run_one_change,
    run_org_development,
)
from aurelis.orgdev.detection import TRIGGERS, scan
from aurelis.orgdev.development import Prediction
from aurelis.orgdev.experiments import STANDING_QUESTIONS, Panel, run_panel
from aurelis.orgdev.invariants import verify_org_invariants
from aurelis.orgdev.metrics import METRICS, agent_metrics, charter_starvation
from aurelis.orgdev.states import (
    EffectVerdict,
    OrgChangeKind,
    OrgChangeState,
    TriggerKind,
)
from aurelis.orgdev.tables import CoverageTransfer, OrgChange
from aurelis.runtime import Runtime


@pytest.fixture
def staffed(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


def _coverage_census(session: sa.orm.Session) -> dict[str, list[str]]:
    rows = session.execute(
        sa.select(AgentCoverage.charter_id, AgentCoverage.agent_ref)
        .join(Agent, Agent.ref == AgentCoverage.agent_ref)
        .where(Agent.state != AgentState.RETIRED)
    ).all()
    census: dict[str, list[str]] = {}
    for charter_id, agent_ref in rows:
        census.setdefault(str(charter_id), []).append(str(agent_ref))
    return census


# ------------------------------------------------------------------ metrics


def test_a_metric_that_cannot_be_taken_is_absent_not_zero(staffed: Runtime) -> None:
    """A zero here is a reason to hire somebody. It has to mean zero.

    The launch Intelligence generalist has no scored forecasts, so its
    calibration is *unmeasurable*; it holds nine charters, so the number of its
    charters with attributable outputs is a measured **zero**. Collapsing those
    two into one number would make the company reorganise itself on the basis
    of a gap in its own instrumentation.
    """
    with staffed.database.session() as session:
        intel = staffed.roster.by_handle(session, "INTEL")
        measured = agent_metrics(session, intel.ref)

    assert measured.get("calibration").value is None
    assert "no forecast" in measured.get("calibration").detail
    assert measured.get("attributable_charters").value == 0
    assert measured.get("breadth").value == 9


def test_an_unmeasurable_reading_never_fires_a_trigger(staffed: Runtime) -> None:
    """Reorganising on the absence of a measurement is not evidence-led."""
    with staffed.database.session() as session:
        hits = scan(session)
    for hit in hits:
        assert hit.reading.value is not None, hit.describe()

    calibration = next(
        t for t in TRIGGERS if t.kind is TriggerKind.CALIBRATION_DECAY
    )
    with staffed.database.session() as session:
        reading = agent_metrics(session, "AG-0004").get("calibration")
    assert reading.value is None
    assert not calibration.fires(reading)


def test_a_prediction_must_name_a_metric_the_company_can_compute() -> None:
    """A prediction nobody can check is not falsifiable."""
    with pytest.raises(Exception, match="no way to compute it"):
        Prediction(
            metric="vibes",
            direction="up",
            magnitude=Decimal(1),
            plan="look at it",
        )
    assert "breadth" in METRICS


def test_a_prediction_of_nothing_is_refused() -> None:
    """Every outcome satisfies a magnitude of zero."""
    with pytest.raises(Exception, match="satisfied by every outcome"):
        Prediction(
            metric="breadth",
            direction="down",
            magnitude=Decimal(0),
            plan="measure it",
        )


# ------------------------------------------------------- coverage is conserved


def test_no_charter_area_is_ever_orphaned(staffed: Runtime) -> None:
    """Every registered charter is held by exactly one working agent."""
    with staffed.database.session() as session:
        census = _coverage_census(session)
    assert set(census) == set(CHARTERS)
    duplicated = {c: holders for c, holders in census.items() if len(holders) != 1}
    assert not duplicated, duplicated


def test_the_database_refuses_to_orphan_a_charter(staffed: Runtime) -> None:
    """Not the service layer. Deleting the last holder is refused outright."""
    with (
        pytest.raises(Exception, match="last agent holding this charter"),
        staffed.database.engine.begin() as conn,
    ):
        conn.execute(
            sa.text(
                "DELETE FROM agent_coverage WHERE charter_id = 'exec.company_manager'"
            )
        )


def test_an_agent_cannot_be_retired_while_it_holds_charters(
    staffed: Runtime,
) -> None:
    """Handover is not a convention fission follows. It is the only exit."""
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
    with (
        pytest.raises(Exception, match="still holds charters"),
        staffed.database.session() as session,
    ):
        staffed.roster.set_state(session, analyst.ref, AgentState.RETIRED)


def test_retiring_an_agent_cannot_take_its_coverage_with_it(
    staffed: Runtime,
) -> None:
    """The cascade is refused too, which is what makes the guarantee hold.

    ``agent_coverage`` cascades from ``agents``, so deleting an agent row would
    silently delete its charters. SQLite fires triggers on cascaded deletes, so
    the orphan guard catches it and the whole deletion is refused.
    """
    with staffed.database.session() as session:
        analyst = staffed.roster.by_handle(session, "INTEL")
        ref = analyst.ref
    with (
        pytest.raises(Exception, match="last agent holding this charter"),
        staffed.database.engine.begin() as conn,
    ):
        conn.execute(sa.text("DELETE FROM agents WHERE ref = :r"), {"r": ref})


def test_coverage_survives_a_fission(staffed: Runtime) -> None:
    """Split anything, and the census is unchanged."""
    with staffed.database.session() as session:
        before = _coverage_census(session)
        intel = staffed.roster.by_handle(session, "INTEL")
        new_ref, report = staffed.handover.split(
            session,
            from_ref=intel.ref,
            handle="NEWSDESK",
            charters=FIRST_SPLIT,
        )
        after = _coverage_census(session)

    assert set(before) == set(after) == set(CHARTERS)
    assert all(len(holders) == 1 for holders in after.values())
    for charter_id in FIRST_SPLIT:
        assert after[charter_id] == [new_ref]
        assert before[charter_id] == [intel.ref]
    assert report.charters == FIRST_SPLIT


def test_coverage_survives_a_fusion(staffed: Runtime) -> None:
    """Merge two agents, and the census is still unchanged."""
    with staffed.database.session() as session:
        intel = staffed.roster.by_handle(session, "INTEL")
        new_ref, _ = staffed.handover.split(
            session,
            from_ref=intel.ref,
            handle="NEWSDESK",
            charters=FIRST_SPLIT,
        )
    with staffed.database.session() as session:
        staffed.handover.merge(session, from_ref=new_ref, into_ref=intel.ref)
        census = _coverage_census(session)
        merged = session.execute(
            sa.select(Agent).where(Agent.ref == new_ref)
        ).scalar_one()

    assert set(census) == set(CHARTERS)
    assert all(len(holders) == 1 for holders in census.values())
    for charter_id in FIRST_SPLIT:
        assert census[charter_id] == [intel.ref]
    assert merged.state == AgentState.RETIRED


def test_every_charter_transfer_is_recorded(staffed: Runtime) -> None:
    """Who was answerable for what, at any past moment, is reconstructable."""
    with staffed.database.session() as session:
        intel = staffed.roster.by_handle(session, "INTEL")
        staffed.handover.split(
            session,
            from_ref=intel.ref,
            handle="NEWSDESK",
            charters=FIRST_SPLIT,
        )
    with staffed.database.session() as session:
        rows = list(session.execute(sa.select(CoverageTransfer)).scalars())
    assert sorted(r.charter_id for r in rows) == sorted(FIRST_SPLIT)
    assert all(r.from_agent == intel.ref for r in rows)
    assert all(r.reason == "fission" for r in rows)


def test_a_split_may_not_empty_its_subject(staffed: Runtime) -> None:
    """Moving all of an agent's coverage is a fusion, not a growth event."""
    with staffed.database.session() as session:
        lead = staffed.roster.by_handle(session, "LEAD-R")
        with pytest.raises(Exception, match="would leave"):
            staffed.handover.split(
                session,
                from_ref=lead.ref,
                handle="NOBODY",
                charters=("research.lead",),
            )


def test_a_split_may_not_span_departments() -> None:
    """An agent belongs to one department; a split across two has no reporting line.

    Tested against the guard directly rather than through a fission, because no
    agent in the launch roster holds charters in two departments — the roster
    itself refuses that. The rule is a pure function and is checked as one.
    """
    from aurelis.orgdev.handover import Handover

    assert (
        Handover._department_of(("gov.registrar", "gov.custodian"))
        is Department.INSTITUTIONAL_GOVERNANCE
    )
    with pytest.raises(Exception, match="across departments"):
        Handover._department_of(("gov.registrar", "exec.company_manager"))


# ----------------------------------------------- the prediction is preregistered


def test_a_locked_prediction_cannot_be_edited(staffed: Runtime) -> None:
    """Not by the service layer, and not by raw SQL.

    A prediction that can be re-aimed once the outcome is known is not a
    prediction, and the whole org-change record would be worth nothing.
    """
    with staffed.database.session() as session:
        hit = next(h for h in scan(session) if h.trigger.kind is TriggerKind.BREADTH)
        change = staffed.orgdev.propose(
            session,
            hit=hit,
            proposed_by="AG-0002",
            prediction=Prediction(
                metric="breadth",
                direction="down",
                magnitude=Decimal(2),
                plan="count charters after the split",
                subject=hit.subject,
            ),
            justification="too wide",
            charters=FIRST_SPLIT,
            new_handle="NEWSDESK",
            kind=OrgChangeKind.FISSION,
        )
        ref = change.ref
        staffed.orgdev.lock(session, ref)

    with (
        pytest.raises(Exception, match="is locked"),
        staffed.database.engine.begin() as conn,
    ):
        conn.execute(
            sa.text(
                "UPDATE org_changes SET predicted_magnitude = '99' WHERE ref = :r"
            ),
            {"r": ref},
        )


def test_a_change_cannot_be_applied_before_it_is_decided(staffed: Runtime) -> None:
    """A structural edit nobody decided on is not a decision."""
    with staffed.database.session() as session:
        hit = next(h for h in scan(session) if h.trigger.kind is TriggerKind.BREADTH)
        change = staffed.orgdev.propose(
            session,
            hit=hit,
            proposed_by="AG-0002",
            prediction=Prediction(
                metric="breadth",
                direction="down",
                magnitude=Decimal(2),
                plan="count charters",
                subject=hit.subject,
            ),
            justification="too wide",
            charters=FIRST_SPLIT,
            new_handle="NEWSDESK",
            kind=OrgChangeKind.FISSION,
        )
        ref = change.ref
        staffed.orgdev.lock(session, ref)
        with pytest.raises(Exception, match="only an approved change"):
            staffed.orgdev.apply(session, ref)

    with (
        pytest.raises(Exception, match="applied once approved"),
        staffed.database.engine.begin() as conn,
    ):
        conn.execute(
            sa.text("UPDATE org_changes SET state = 'applied' WHERE ref = :r"),
            {"r": ref},
        )


def test_an_agent_may_not_propose_a_change_to_its_own_record(
    staffed: Runtime,
) -> None:
    """Self-modification would make the growth mechanism unauditable."""
    with staffed.database.session() as session:
        hit = next(h for h in scan(session) if h.trigger.kind is TriggerKind.BREADTH)
        with pytest.raises(Exception, match="its own record"):
            staffed.orgdev.propose(
                session,
                hit=hit,
                proposed_by=hit.subject,
                prediction=Prediction(
                    metric="breadth",
                    direction="down",
                    magnitude=Decimal(1),
                    plan="count",
                    subject=hit.subject,
                ),
                justification="I would like fewer charters",
                charters=FIRST_SPLIT,
                new_handle="NEWSDESK",
                kind=OrgChangeKind.FISSION,
            )


def test_the_room_never_sees_an_unlocked_prediction(staffed: Runtime) -> None:
    """A change must be locked before it can be decided."""
    with staffed.database.session() as session:
        hit = next(h for h in scan(session) if h.trigger.kind is TriggerKind.BREADTH)
        change = staffed.orgdev.propose(
            session,
            hit=hit,
            proposed_by="AG-0002",
            prediction=Prediction(
                metric="breadth",
                direction="down",
                magnitude=Decimal(2),
                plan="count",
                subject=hit.subject,
            ),
            justification="too wide",
            charters=FIRST_SPLIT,
            new_handle="NEWSDESK",
            kind=OrgChangeKind.FISSION,
        )
        with pytest.raises(Exception, match="must be locked"):
            staffed.orgdev.decide(
                session,
                change.ref,
                approved=True,
                decided_by="AG-0003",
                meeting_ref="MTG-0001",
            )


def test_the_org_invariants_are_installed(staffed: Runtime) -> None:
    with staffed.database.engine.begin() as connection:
        assert verify_org_invariants(connection) == ()


# ------------------------------- acceptance: propose, decide, apply, measure


def test_the_company_changes_itself_and_measures_the_result(
    staffed: Runtime,
) -> None:
    """The acceptance criterion, end to end, twice.

    Twice because one run cannot show that the verdict discriminates. The first
    change is sensible, clean and **fails its prediction**; the second one
    holds. Both are recorded.
    """
    outcome = run_org_development(staffed)

    assert len(outcome.steps) == 2
    first, second = outcome.steps
    assert first.effect.verdict is EffectVerdict.NO_CHANGE
    assert second.effect.verdict is EffectVerdict.IMPROVED
    assert outcome.discriminates

    assert first.breadth_before == 9
    assert first.breadth_after == 7
    assert second.breadth_after == 1
    assert outcome.coverage_intact

    with staffed.database.session() as session:
        rows = staffed.orgdev.history(session)
        census = _coverage_census(session)
    assert [r.state for r in rows] == [OrgChangeState.MEASURED] * 2
    assert set(census) == set(CHARTERS)
    assert all(len(holders) == 1 for holders in census.values())


def test_a_failed_prediction_is_recorded_as_a_failure(staffed: Runtime) -> None:
    """A company that only kept the changes that worked would learn nothing."""
    step = run_one_change(
        staffed, charters=FIRST_SPLIT, handle="NEWSDESK", note="a sensible split"
    )
    assert step.effect.verdict is EffectVerdict.NO_CHANGE
    assert not step.prediction_held

    with staffed.database.session() as session:
        row = session.execute(
            sa.select(OrgChange).where(OrgChange.ref == step.change_ref)
        ).scalar_one()
    assert row.effect == EffectVerdict.NO_CHANGE.value
    assert row.baseline == "0"
    assert row.realised == "0"
    assert "stayed at 0" in row.effect_detail


def test_a_change_is_decided_in_a_room(staffed: Runtime) -> None:
    """An applied change with no meeting behind it is an unreviewed edit."""
    step = run_one_change(
        staffed, charters=FIRST_SPLIT, handle="NEWSDESK", note="a sensible split"
    )
    with staffed.database.session() as session:
        row = session.execute(
            sa.select(OrgChange).where(OrgChange.ref == step.change_ref)
        ).scalar_one()
    assert row.meeting_ref == step.meeting_ref
    assert row.decided_by

    with (
        pytest.raises(Exception, match="applied_was_decided_in_a_room"),
        staffed.database.engine.begin() as conn,
    ):
        conn.execute(
            sa.text("UPDATE org_changes SET meeting_ref = NULL WHERE ref = :r"),
            {"r": step.change_ref},
        )


def test_a_split_agent_is_onboarded_before_it_works(staffed: Runtime) -> None:
    """A fission hire is a hire: it runs the scenario suite first (ADR-0005)."""
    step = run_one_change(
        staffed, charters=SECOND_SPLIT, handle="ANALYSIS", note="split the analysts"
    )
    with staffed.database.session() as session:
        record = staffed.onboarding.latest(session, step.new_agent)
        agent = session.execute(
            sa.select(Agent).where(Agent.ref == step.new_agent)
        ).scalar_one()
    assert record is not None
    assert record.verdict == step.new_agent_verdict
    assert agent.state == AgentState.ACTIVE


def test_the_handover_says_what_it_did_not_move(staffed: Runtime) -> None:
    """A task already claimed cannot be handed over, and is reported.

    The queue can reassign a row; it cannot hand over what the worker was
    part-way through. Silently moving one would lose that work without saying
    so.
    """
    from aurelis.core.enums import BudgetPeriod, BudgetScope
    from aurelis.platform.queue.queue import Spend
    from aurelis.runtime import COMPANY_SCOPE_ID

    with staffed.database.session() as session:
        intel = staffed.roster.by_handle(session, "INTEL")
        staffed.budget.open(
            session,
            scope=BudgetScope.COMPANY,
            scope_id=COMPANY_SCOPE_ID,
            usd=Decimal("5"),
            tokens=500_000,
            period=BudgetPeriod.LIFETIME,
        )
        staffed.queue.enqueue(
            session,
            kind="intel.briefing",
            assignee=intel.ref,
            subject="a briefing",
            allowance=Spend(Decimal("0.01"), 1_000),
        )
        staffed.queue.enqueue(
            session,
            kind="intel.briefing",
            assignee=intel.ref,
            subject="another briefing",
            allowance=Spend(Decimal("0.01"), 1_000),
        )
        staffed.queue.claim(session, worker=intel.ref, assignee=intel.ref)

    with staffed.database.session() as session:
        _, report = staffed.handover.split(
            session,
            from_ref=intel.ref,
            handle="NEWSDESK",
            charters=FIRST_SPLIT,
        )
    assert len(report.tasks_reassigned) == 1
    assert len(report.tasks_left_in_flight) == 1
    assert "left in flight" in report.describe()


# ----------------------------------------- experiments on the company's shape


def test_more_agents_help_only_when_they_widen_the_question(
    staffed: Runtime,
) -> None:
    """CLAUDE.md 16, as arithmetic.

    A second seat with a specialty the room already holds moves nothing at all
    — not a little, exactly nothing, because the union of a set with a subset
    of itself is the set. A seat that covers defects nobody else was asked
    about moves the count.
    """
    suite = staffed.org_experiments.suite
    one = run_panel(Panel("one", ("strategy.critic",)), suite)
    duplicate = run_panel(
        Panel("two", ("strategy.critic", "strategy.adversarial")), suite
    )
    assert duplicate.score.caught == one.score.caught
    assert duplicate.score.false_alarms == one.score.false_alarms

    narrow = run_panel(
        Panel("research only", ("research.backtest", "research.statistical")), suite
    )
    widened = run_panel(
        Panel(
            "research + adversarial",
            ("research.backtest", "research.statistical", "strategy.adversarial"),
        ),
        suite,
    )
    assert widened.score.caught > narrow.score.caught
    assert widened.score.false_alarms == narrow.score.false_alarms


def test_an_org_experiment_is_recorded_whichever_way_it_comes_out(
    staffed: Runtime,
) -> None:
    """Including — especially — when the answer is no difference."""
    verdicts = set()
    with staffed.database.session() as session:
        for question, control, treatment in STANDING_QUESTIONS:
            row = staffed.org_experiments.run(
                session, question=question, control=control, treatment=treatment
            )
            verdicts.add(row.verdict)
    assert "no_difference" in verdicts
    assert "treatment_better" in verdicts


def test_every_panel_names_charters_that_exist() -> None:
    for _, control, treatment in STANDING_QUESTIONS:
        for panel in (control, treatment):
            for charter_id in panel.members:
                assert charter_id in CHARTERS, charter_id


# ------------------------------------------------------------------ reporting


def test_starvation_distinguishes_orphaned_from_unattributable(
    staffed: Runtime,
) -> None:
    """Two different problems with two different fixes."""
    with staffed.database.session() as session:
        report = charter_starvation(session)
    assert set(report) == set(CHARTERS)
    assert not [c for c, why in report.items() if why.startswith("ORPHANED")]
    unattributable = [c for c, why in report.items() if why.startswith("unattrib")]
    attributable = [c for c, why in report.items() if why.startswith("attributable")]
    assert unattributable and attributable


def test_a_new_department_cannot_be_invented_by_a_split(staffed: Runtime) -> None:
    """The department comes from the charters, not from the caller."""
    with staffed.database.session() as session:
        intel = staffed.roster.by_handle(session, "INTEL")
        new_ref, _ = staffed.handover.split(
            session,
            from_ref=intel.ref,
            handle="NEWSDESK",
            charters=FIRST_SPLIT,
            seniority=Seniority.SENIOR,
        )
        row = session.execute(
            sa.select(Agent).where(Agent.ref == new_ref)
        ).scalar_one()
    assert row.department == Department.MARKET_INTELLIGENCE.value
