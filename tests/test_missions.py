"""Missions, projects, task dependencies, and the three-agent chain.

The M2 acceptance criteria. The gate tests matter most: a mission that could
start work without a kickoff, or close without a retrospective, would make
meeting at the start and end a convention rather than a property.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aurelis.core.enums import EventKind, TaskStatus
from aurelis.core.errors import IntegrityViolation
from aurelis.intel.briefing import TASK_KIND as BRIEFING_TASK
from aurelis.intel.tables import MarketObservation
from aurelis.missions.pipeline import Step, plan_project
from aurelis.missions.states import KickoffKind, MissionState, ProjectState, may_transition
from aurelis.missions.tables import Mission, WorkItem
from aurelis.platform.budget.ledger import Spend
from aurelis.platform.db.tables import Task
from aurelis.research.triage import QUESTION_TASK, TRIAGE_TASK
from aurelis.runtime import Runtime


@pytest.fixture
def company(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


def _open_mission(runtime: Runtime, **kwargs: object) -> str:
    with runtime.database.session() as session:
        mission = runtime.missions.open_mission(
            session,
            objective=str(kwargs.pop("objective", "Study something")),
            budget_tokens=int(kwargs.pop("budget_tokens", 100_000)),  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )
        return mission.ref


# --------------------------------------------------------- state machines


def test_transitions_are_a_closed_table() -> None:
    assert may_transition("planning", "active")
    assert not may_transition("planning", "closed")
    assert not may_transition("closed", "active")


def test_an_unknown_state_answers_no_rather_than_raising() -> None:
    assert not may_transition("daydreaming", "active")
    assert not may_transition("active", "transcendent")


def test_reviewing_can_reopen_a_mission() -> None:
    """A retrospective that finds unfinished work should not force a new
    mission that loses the history."""
    assert may_transition("reviewing", "active")


def test_budget_exhausted_is_a_real_state_not_an_error() -> None:
    assert may_transition("active", "budget_exhausted")
    assert may_transition("budget_exhausted", "reviewing")


# ------------------------------------------------------------- the gates


def test_a_mission_cannot_start_work_without_a_kickoff(company: Runtime) -> None:
    """The M2 acceptance criterion."""
    ref = _open_mission(company)
    with company.database.session() as session:
        mission = company.missions.mission(session, ref)
        assert mission.state == MissionState.PLANNING
        assert mission.kickoff_ref is None
        with pytest.raises(IntegrityViolation, match="without a kickoff"):
            company.missions.transition(session, ref, MissionState.ACTIVE)


def test_a_kickoff_unblocks_the_transition(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        company.missions.record_kickoff(
            session, subject_ref=ref, plan="Do the thing, then check it."
        )
        company.missions.transition(session, ref, MissionState.ACTIVE)
        assert company.missions.mission(session, ref).state == MissionState.ACTIVE


def test_an_empty_kickoff_is_refused(company: Runtime) -> None:
    """A blank plan would satisfy the gate without doing its job."""
    ref = _open_mission(company)
    with company.database.session() as session:  # noqa: SIM117
        with pytest.raises(IntegrityViolation, match="must carry a plan"):
            company.missions.record_kickoff(session, subject_ref=ref, plan="   ")


def test_the_kickoff_records_who_produced_it(company: Runtime) -> None:
    """At M3 a meeting produces this; the record must distinguish the two."""
    ref = _open_mission(company)
    with company.database.session() as session:
        kickoff = company.missions.record_kickoff(
            session, subject_ref=ref, plan="A plan.", kind=KickoffKind.OPERATOR
        )
    assert kickoff.kind == KickoffKind.OPERATOR
    assert kickoff.authorised_by == "operator"
    assert kickoff.artifact_digest


def test_a_mission_cannot_close_without_a_retrospective(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        company.missions.record_kickoff(session, subject_ref=ref, plan="A plan.")
        company.missions.transition(session, ref, MissionState.ACTIVE)
        company.missions.transition(session, ref, MissionState.REVIEWING)
        with pytest.raises(IntegrityViolation, match="without a retrospective"):
            company.missions.transition(session, ref, MissionState.CLOSED)


def test_a_retrospective_records_the_outcomes_as_they_were(company: Runtime) -> None:
    """Including the failures. A retrospective that kept only the successes
    would be the graveyard being quietly emptied."""
    ref = _open_mission(company)
    with company.database.session() as session:
        company.missions.record_kickoff(session, subject_ref=ref, plan="A plan.")
        company.missions.transition(session, ref, MissionState.ACTIVE)
        project = company.missions.open_project(
            session, mission_ref=ref, name="P", budget_tokens=1_000
        )
        task = company.queue.enqueue(session, kind="k")
        company.missions.place(session, task_ref=task.ref, project_ref=project.ref)
        claimed = company.queue.claim(session, worker="W")
        assert claimed is not None
        company.queue.fail(session, claimed, reason="did not work")

        company.missions.transition(session, ref, MissionState.REVIEWING)
        retro = company.missions.record_retrospective(
            session, subject_ref=ref, summary="It failed.", lessons=("Try harder.",)
        )
    assert retro.outcome_counts["failed"] == 1
    assert retro.outcome_counts["succeeded"] == 0


def test_cancelling_requires_a_reason(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:  # noqa: SIM117
        with pytest.raises(IntegrityViolation, match="requires a stated reason"):
            company.missions.transition(session, ref, MissionState.CANCELLED)


def test_an_illegal_transition_is_refused(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:  # noqa: SIM117
        with pytest.raises(IntegrityViolation, match="cannot go planning -> closed"):
            company.missions.transition(session, ref, MissionState.CLOSED)


# ----------------------------------------------------------- decomposition


def test_a_project_takes_a_slice_of_its_mission(company: Runtime) -> None:
    ref = _open_mission(company, budget_tokens=10_000)
    with company.database.session() as session:
        project = company.missions.open_project(
            session, mission_ref=ref, name="P", budget_tokens=4_000
        )
    assert project.mission_ref == ref
    assert project.ref.startswith("PRJ-")


def test_projects_cannot_overallocate_the_mission(company: Runtime) -> None:
    ref = _open_mission(company, budget_tokens=10_000)
    with company.database.session() as session:
        company.missions.open_project(
            session, mission_ref=ref, name="A", budget_tokens=7_000
        )
        with pytest.raises(IntegrityViolation, match="would take mission"):
            company.missions.open_project(
                session, mission_ref=ref, name="B", budget_tokens=7_000
            )


def test_work_items_link_tasks_to_the_hierarchy(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        project = company.missions.open_project(
            session, mission_ref=ref, name="P", budget_tokens=1_000
        )
        task = company.queue.enqueue(session, kind="k")
        company.missions.place(session, task_ref=task.ref, project_ref=project.ref)
        item = session.execute(sa.select(WorkItem)).scalars().one()
    assert item.mission_ref == ref
    assert item.project_ref == project.ref


# ------------------------------------------------------------- dependencies


def test_a_task_with_an_unmet_dependency_is_not_claimable(company: Runtime) -> None:
    with company.database.session() as session:
        first = company.queue.enqueue(session, kind="a", assignee="AG-0001")
        second = company.queue.enqueue(
            session, kind="b", assignee="AG-0002", depends_on=(first.ref,)
        )
        assert company.queue.claim(session, worker="AG-0002", assignee="AG-0002") is None
        assert company.queue.blocked_by(session, second.ref) == [first.ref]


def test_a_dependency_releases_when_it_succeeds(company: Runtime) -> None:
    with company.database.session() as session:
        first = company.queue.enqueue(session, kind="a", assignee="AG-0001")
        company.queue.enqueue(session, kind="b", assignee="AG-0002", depends_on=(first.ref,))

        claimed = company.queue.claim(session, worker="AG-0001", assignee="AG-0001")
        assert claimed is not None
        company.queue.succeed(session, claimed)

        released = company.queue.claim(session, worker="AG-0002", assignee="AG-0002")
        assert released is not None
        assert released.kind == "b"


def test_a_failed_dependency_does_not_release_the_dependent(company: Runtime) -> None:
    with company.database.session() as session:
        first = company.queue.enqueue(session, kind="a", assignee="AG-0001")
        company.queue.enqueue(session, kind="b", assignee="AG-0002", depends_on=(first.ref,))
        claimed = company.queue.claim(session, worker="AG-0001", assignee="AG-0001")
        assert claimed is not None
        company.queue.fail(session, claimed, reason="broke")
        assert company.queue.claim(session, worker="AG-0002", assignee="AG-0002") is None


def test_a_stranded_dependent_is_cancelled_not_left_waiting(company: Runtime) -> None:
    """A chain that stalls forever is indistinguishable from one nobody started."""
    with company.database.session() as session:
        first = company.queue.enqueue(session, kind="a", assignee="AG-0001")
        second = company.queue.enqueue(
            session, kind="b", assignee="AG-0002", depends_on=(first.ref,)
        )
        claimed = company.queue.claim(session, worker="AG-0001", assignee="AG-0001")
        assert claimed is not None
        company.queue.fail(session, claimed, reason="broke")

        cancelled = company.queue.cancel_stranded(session)
        session.refresh(second)

    assert [t.ref for t in cancelled] == [second.ref]
    assert second.status == TaskStatus.CANCELLED
    assert first.ref in (second.failure_reason or "")


def test_a_task_cannot_depend_on_itself(company: Runtime) -> None:
    with company.database.session() as session:
        table = sa.text(
            "INSERT INTO task_dependencies (task_ref, depends_on_ref, created_at) "
            "VALUES ('TSK-0001','TSK-0001','2026-01-01 00:00:00')"
        )
        with pytest.raises(Exception, match="ck_task_not_self_dependent"):
            session.execute(table)


# ---------------------------------------------------------------- planning


def test_a_plan_names_its_steps_and_wires_them(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        project = company.missions.open_project(
            session, mission_ref=ref, name="P", budget_tokens=30_000
        )
        tasks = plan_project(
            session,
            company.missions,
            company.queue,
            project_ref=project.ref,
            steps=(
                Step("a", "AG-0001", name="first"),
                Step("b", "AG-0002", after=("first",), name="second"),
            ),
        )
        assert company.queue.blocked_by(session, tasks[1].ref) == [tasks[0].ref]


def test_a_plan_cannot_depend_on_an_undeclared_step(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        project = company.missions.open_project(
            session, mission_ref=ref, name="P", budget_tokens=30_000
        )
        with pytest.raises(IntegrityViolation, match="not an earlier step"):
            plan_project(
                session,
                company.missions,
                company.queue,
                project_ref=project.ref,
                steps=(Step("a", "AG-0001", after=("nowhere",), name="only"),),
            )


def test_two_steps_cannot_share_a_name(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        project = company.missions.open_project(
            session, mission_ref=ref, name="P", budget_tokens=30_000
        )
        with pytest.raises(IntegrityViolation, match="both called"):
            plan_project(
                session,
                company.missions,
                company.queue,
                project_ref=project.ref,
                steps=(Step("a", "AG-0001", name="x"), Step("b", "AG-0002", name="x")),
            )


# ---------------------------------------------------------------- progress


def test_progress_is_computed_and_separates_failures(company: Runtime) -> None:
    """No single reassuring percentage."""
    ref = _open_mission(company)
    with company.database.session() as session:
        project = company.missions.open_project(
            session, mission_ref=ref, name="P", budget_tokens=9_000
        )
        for kind in ("a", "b", "c"):
            task = company.queue.enqueue(session, kind=kind, assignee="W")
            company.missions.place(session, task_ref=task.ref, project_ref=project.ref)

        good = company.queue.claim(session, worker="W", assignee="W")
        assert good is not None
        company.queue.succeed(session, good)
        bad = company.queue.claim(session, worker="W", assignee="W")
        assert bad is not None
        company.queue.fail(session, bad, reason="no")

        progress = company.missions.progress(session, ref)

    assert progress.total == 3
    assert progress.succeeded == 1
    assert progress.failed == 1
    assert progress.in_flight == 1
    assert "1 failed" in progress.describe()


def test_progress_on_an_empty_mission_says_so(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        assert company.missions.progress(session, ref).describe() == "no work yet"


def test_spend_is_attributed_to_the_mission(company: Runtime) -> None:
    """The envelope travels with the task, so project work counts upward."""
    ref = _open_mission(company)
    with company.database.session() as session:
        project = company.missions.open_project(
            session, mission_ref=ref, name="P", budget_tokens=30_000
        )
        envelope = company.missions.envelope_for(session, project.ref)
        company.budget.record(session, envelope, Spend(tokens=1_234), reason="test")
        assert company.missions.spent(session, ref).tokens == 1_234
        assert company.missions.spent(session, project.ref).tokens == 1_234


# ------------------------------------------------------ the three-agent chain


def _run_chain(runtime: Runtime, *, bars: int = 24) -> tuple[str, list[str]]:
    with runtime.database.session() as session:
        intel = runtime.roster.by_handle(session, "INTEL")
        quant = runtime.roster.by_handle(session, "QUANT")
        lead = runtime.roster.by_handle(session, "LEAD-R")
        for agent in (intel, quant, lead):
            runtime.worker.open_daily_budget(session, agent, tokens=100_000)

        mission = runtime.missions.open_mission(
            session, objective="Review the desk", budget_tokens=60_000
        )
        runtime.missions.record_kickoff(
            session, subject_ref=mission.ref, plan="Brief, ask, decide."
        )
        runtime.missions.transition(session, mission.ref, MissionState.ACTIVE)
        project = runtime.missions.open_project(
            session, mission_ref=mission.ref, name="Review", budget_tokens=40_000
        )
        plan_project(
            session,
            runtime.missions,
            runtime.queue,
            project_ref=project.ref,
            steps=(
                Step(BRIEFING_TASK, intel.ref, {"bars": bars}, name="brief"),
                Step(
                    QUESTION_TASK,
                    quant.ref,
                    {"bars": bars * 2, "ask": lead.ref},
                    after=("brief",),
                    name="question",
                ),
                Step(TRIAGE_TASK, lead.ref, {}, after=("question",), name="triage"),
            ),
        )
        actors = [intel.ref, quant.ref, lead.ref]
        mission_ref = mission.ref

    for _ in range(8):
        moved = False
        with runtime.database.session() as session:
            runtime.queue.cancel_stranded(session)
            for ref in actors:
                if runtime.worker.run_once(session, runtime.roster.get(session, ref)):
                    moved = True
        if not moved:
            break
    return mission_ref, actors


def test_three_agents_complete_a_chain(company: Runtime) -> None:
    """The M2 demonstration: brief -> question -> triage, self-sequencing."""
    mission_ref, _ = _run_chain(company)
    with company.database.session() as session:
        progress = company.missions.progress(session, mission_ref)
    assert progress.total == 3
    assert progress.succeeded == 3, progress.describe()


def test_the_chain_runs_in_dependency_order(company: Runtime) -> None:
    mission_ref, _ = _run_chain(company)
    with company.database.session() as session:
        tasks = (
            session.execute(sa.select(Task).order_by(Task.finished_at, Task.ref))
            .scalars()
            .all()
        )
    order = [t.kind for t in tasks if t.finished_at is not None]
    assert order == [BRIEFING_TASK, QUESTION_TASK, TRIAGE_TASK]


def test_the_researcher_works_from_the_analysts_observation(company: Runtime) -> None:
    """Genuine collaboration: QUANT cites an observation it did not write."""
    from aurelis.comms.tables import Message, MessageKind

    _run_chain(company)
    with company.database.session() as session:
        observation = session.execute(sa.select(MarketObservation)).scalars().one()
        question = session.execute(
            sa.select(Message).where(Message.kind == MessageKind.QUESTION.value)
        ).scalars().one()

    assert observation.author != question.from_agent
    assert observation.ref in question.evidence_refs


def test_the_lead_decides_and_the_decision_cites_the_question(company: Runtime) -> None:
    from aurelis.comms.tables import Message, MessageKind

    _run_chain(company)
    with company.database.session() as session:
        question = session.execute(
            sa.select(Message).where(Message.kind == MessageKind.QUESTION.value)
        ).scalars().one()
        decision = session.execute(
            sa.select(Message).where(Message.kind == MessageKind.DECISION.value)
        ).scalars().one()

    assert question.ref in decision.evidence_refs
    assert decision.subject.endswith(("pursue", "decline"))


def test_every_artifact_in_the_chain_is_traceable(company: Runtime) -> None:
    """The M2 acceptance criterion: every artifact traceable."""
    mission_ref, _ = _run_chain(company)
    with company.database.session() as session:
        items = session.execute(
            sa.select(WorkItem).where(WorkItem.mission_ref == mission_ref)
        ).scalars().all()
        for item in items:
            task = session.execute(
                sa.select(Task).where(Task.ref == item.task_ref)
            ).scalar_one()
            assert task.result_digest, f"{task.ref} produced no artifact"
            assert company.artifacts.exists(task.result_digest)


def test_the_chain_spends_against_the_mission(company: Runtime) -> None:
    mission_ref, _ = _run_chain(company)
    with company.database.session() as session:
        spent = company.missions.spent(session, mission_ref)
    assert spent.tokens > 0


def test_the_chain_leaves_a_verifiable_ledger(company: Runtime) -> None:
    _run_chain(company)
    with company.database.session() as session:
        assert company.ledger.verify(session).ok


def test_opening_a_mission_is_recorded(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        kinds = [e.kind for e in company.ledger.for_subject(session, ref)]
    assert EventKind.MISSION_OPENED.value in kinds


def test_a_closed_mission_takes_no_further_projects(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        company.missions.record_kickoff(session, subject_ref=ref, plan="A plan.")
        company.missions.transition(session, ref, MissionState.ACTIVE)
        company.missions.transition(session, ref, MissionState.REVIEWING)
        company.missions.record_retrospective(session, subject_ref=ref, summary="Done.")
        company.missions.transition(session, ref, MissionState.CLOSED)
        with pytest.raises(IntegrityViolation, match="no further projects"):
            company.missions.open_project(session, mission_ref=ref, name="Late")


def test_a_project_has_its_own_gates(company: Runtime) -> None:
    ref = _open_mission(company)
    with company.database.session() as session:
        company.missions.record_kickoff(session, subject_ref=ref, plan="A plan.")
        company.missions.transition(session, ref, MissionState.ACTIVE)
        project = company.missions.open_project(
            session, mission_ref=ref, name="P", budget_tokens=1_000
        )
        with pytest.raises(IntegrityViolation, match="without a kickoff"):
            company.missions.transition(session, project.ref, ProjectState.ACTIVE)


def test_missions_are_not_append_only(company: Runtime) -> None:
    """Missions are state, not history: they must remain updatable."""
    ref = _open_mission(company)
    with company.database.engine.begin() as conn:
        conn.execute(sa.text("UPDATE missions SET priority = priority"))
    with company.database.session() as session:
        assert session.execute(sa.select(Mission).where(Mission.ref == ref)).scalar_one()


# ----------------------------------------------------------- the working day


def test_standing_jobs_address_their_agent(company: Runtime) -> None:
    """A scheduled task addressed to nobody would sit in the queue looking
    like work in progress."""
    from aurelis.missions.schedule import register_standing_jobs

    with company.database.session() as session:
        registered = register_standing_jobs(session, company.scheduler, company.roster)
        fired = company.scheduler.tick(session)
        intel = company.roster.by_handle(session, "INTEL")

    assert "desk.crypto.briefing" in registered
    assert len(fired) == 1
    assert fired[0].assignee == intel.ref
    assert fired[0].kind == BRIEFING_TASK


def test_the_daily_briefing_actually_runs(company: Runtime) -> None:
    from aurelis.missions.schedule import register_standing_jobs

    with company.database.session() as session:
        register_standing_jobs(session, company.scheduler, company.roster)
        company.scheduler.tick(session)
        intel = company.roster.by_handle(session, "INTEL")
        company.worker.open_daily_budget(session, intel, tokens=50_000)
        result = company.worker.run_once(session, intel)

    assert result is not None
    with company.database.session() as session:
        assert session.execute(sa.select(MarketObservation)).scalars().one()


def test_standing_jobs_are_idempotent(company: Runtime) -> None:
    """Restarting must not reset the schedule and delay the company a day."""
    from aurelis.missions.schedule import register_standing_jobs

    with company.database.session() as session:
        register_standing_jobs(session, company.scheduler, company.roster)
        company.scheduler.tick(session)
        register_standing_jobs(session, company.scheduler, company.roster)
        assert company.scheduler.tick(session) == []


def test_a_job_for_an_unhired_agent_is_skipped(runtime: Runtime) -> None:
    """Registering against nobody would queue work no charter owns."""
    from aurelis.missions.schedule import register_standing_jobs

    with runtime.database.session() as session:
        assert register_standing_jobs(session, runtime.scheduler, runtime.roster) == []
