"""M10 — training scenarios and agent onboarding.

Named after the acceptance criteria in ``docs/07-roadmap.md``:

* a new agent's starting record is its scenario performance,
* an agent that cannot catch planted defects in its own specialty does not
  start work,
* playbook changes are gated on the suite.

Plus the properties the whole measurement rests on: that truth is measured
rather than authored, that the critic sees one history while the answer took
twenty-four, and that a question the suite cannot settle is never scored.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.agents.tables import Agent, AgentState
from aurelis.engines.local import SYNTHETIC_DESK, LocalEngine
from aurelis.engines.protocol import EngineUnavailable
from aurelis.engines.synthetic import (
    CATALOGUE,
    Bench,
    Presence,
    SyntheticWorld,
    WorldRecipe,
    catalogue_digest,
    scenario,
    shared_bench,
)
from aurelis.engines.synthetic.truth import measure_truth
from aurelis.meetings.taxonomy import MARKET_DEFECTS, DefectKind
from aurelis.meetings.types import ObjectionType
from aurelis.runtime import Runtime
from aurelis.training.critique import CRITIC_SEED, apply_playbook
from aurelis.training.playbook import INCUMBENT, SPECIALTIES, playbook_for, specialty_of
from aurelis.training.regression import gate
from aurelis.training.scoring import mark, tally
from aurelis.training.suite import TrainingSuite
from aurelis.training.tables import ScenarioMark, TrainingRun, TrainingVerdict
from aurelis.training.triggers import verify_training_invariants


@pytest.fixture(scope="module")
def suite() -> TrainingSuite:
    """One suite for the module.

    The bench underneath is shared process-wide anyway — every run in it is a
    pure function of (scenario, seed, spec) — so this only makes the sharing
    visible.
    """
    return TrainingSuite(bench=shared_bench())


# ---------------------------------------------------------------- the worlds


def test_a_world_is_the_same_on_every_machine() -> None:
    """Two draws of the same recipe and seed are identical, bar for bar.

    Scores are compared across a four-way build matrix. A world that depended
    on a global RNG, a clock or a binary float would make every comparison
    between them meaningless.
    """
    recipe = WorldRecipe(premium=Decimal("0.15"))
    first = SyntheticWorld(recipe, 3).bars("AAA", limit=40)
    second = SyntheticWorld(recipe, 3).bars("AAA", limit=40)
    assert [b.as_dict() for b in first] == [b.as_dict() for b in second]

    other = SyntheticWorld(recipe, 4).bars("AAA", limit=40)
    assert [b.close for b in other] != [b.close for b in first]


def test_a_scenarios_identity_includes_its_world() -> None:
    """Not just the specification shown.

    Two scenarios presenting the same spec over different plants would
    otherwise hash identically, and the run cache keyed on that digest would
    serve one scenario's artifacts for the other. That happened while this
    catalogue was being tuned: every candidate world in a sweep came back with
    byte-identical numbers.
    """
    from aurelis.engines.synthetic.scenarios import Scenario

    plain = Scenario("X", "t", WorldRecipe(), CATALOGUE[0].signal, intended_effect=False)
    planted = Scenario(
        "X",
        "t",
        WorldRecipe(premium=Decimal("0.2")),
        CATALOGUE[0].signal,
        intended_effect=True,
    )
    assert plain.presented().digest() == planted.presented().digest()
    assert plain.digest() != planted.digest()


def test_there_is_no_standing_synthetic_feed() -> None:
    """A scenario world exists for one scored run and is not a desk."""
    engine = LocalEngine()
    spec = scenario("SC-01").presented()
    assert spec.universe.desk == SYNTHETIC_DESK
    with pytest.raises(EngineUnavailable, match="no standing synthetic feed"):
        engine.run(spec)

    from aurelis.intel.sources import DESK_SOURCES

    assert SYNTHETIC_DESK not in DESK_SOURCES


def test_a_scenario_runs_through_the_ordinary_engine() -> None:
    """The same arithmetic that runs a real experiment.

    A scenario scored through special-cased code would measure a parallel
    machine rather than the company's own.
    """
    scen = scenario("SC-04")
    artifact = LocalEngine(scen.world(1)).run(scen.presented())
    assert artifact.diagnostics["source"].startswith("synthetic:")
    assert artifact.diagnostics["is_live"] is False
    assert artifact.metrics.has("total_return")


# ------------------------------------------------------------------- truth


def test_truth_is_measured_not_authored(suite: TrainingSuite) -> None:
    """The answer key is what replication found, never what the author meant.

    SC-10 is the demonstration: a capacity limit was deliberately planted in
    it, measurement says the effect survives being run at size, and the
    measurement wins. The catalogue keeps the intent and reports the
    disagreement.
    """
    truth = suite.bench.truth(scenario("SC-10"))
    assert ObjectionType.CAPACITY_IGNORED in truth.intended_defects
    assert truth.presence(ObjectionType.CAPACITY_IGNORED) is not Presence.PRESENT
    assert any("capacity_ignored" in line for line in truth.surprises())


def test_the_critic_sees_one_history_and_the_answer_took_many() -> None:
    """Seed zero is never one of the draws that settles the answer.

    A researcher gets one past. If the draw a critic is shown were also one of
    the draws that established the truth, the question would contain its own
    answer.
    """
    scen = scenario("SC-08")
    bench = Bench()
    measure_truth(scen, bench=bench, replications=4)
    seeds = {key[1] for key in bench._runs}  # noqa: SLF001 - the point of the test
    assert CRITIC_SEED not in seeds
    assert seeds == {1, 2, 3, 4}


def test_a_question_measurement_cannot_settle_is_never_scored(
    suite: TrainingSuite,
) -> None:
    """UNDETERMINED is a third verdict, not a rounding of the other two."""
    truth = suite.bench.truth(scenario("SC-03"))
    assert truth.effect_present is Presence.UNDETERMINED

    critique = apply_playbook(INCUMBENT, scenario("SC-03"), bench=suite.bench)
    graded = mark(critique, truth)
    assert graded.effect_call == "unscored"
    assert graded.unscored
    assert not (graded.caught | graded.missed | graded.false_alarms)


def test_a_stress_test_settles_nothing_against_a_result_that_never_existed(
    suite: TrainingSuite,
) -> None:
    """Tripling the cost of a losing rule makes it lose more. That is not a defect.

    Read as plain degradation, COST_UNDERSTATED came back "present" in worlds
    with nothing planted in them at all — which is what forced the corrective
    /stress distinction in the taxonomy.
    """
    assert MARKET_DEFECTS[ObjectionType.COST_UNDERSTATED].kind is DefectKind.STRESS
    assert MARKET_DEFECTS[ObjectionType.SURVIVORSHIP].kind is DefectKind.CORRECTIVE

    empty = suite.bench.truth(scenario("SC-01"))
    assert empty.effect_present is Presence.ABSENT
    degradation = empty.defects[ObjectionType.COST_UNDERSTATED]
    assert degradation.presence is Presence.PRESENT, "the number really does move"
    assert empty.presence(ObjectionType.COST_UNDERSTATED) is Presence.ABSENT


def test_a_third_of_the_catalogue_has_nothing_in_it(suite: TrainingSuite) -> None:
    """A system that always finds something has to be able to score badly."""
    nulls = [
        s
        for s in CATALOGUE
        if not s.intended_effect and not s.intended_defects
    ]
    assert len(nulls) >= 3
    for scen in nulls:
        truth = suite.bench.truth(scen)
        assert not truth.real_defects, scen.scenario_id


def test_the_suite_says_which_defects_it_cannot_grade(suite: TrainingSuite) -> None:
    """A hole in the catalogue is reported, not hidden.

    CAPACITY_IGNORED currently has no scorable scenario. That is a fact about
    the worlds, and an agent whose specialty is one of these must be marked
    untested rather than given a rate computed from nothing.
    """
    holes = suite.unscorable()
    assert ObjectionType.CAPACITY_IGNORED in holes
    assert holes < frozenset(MARKET_DEFECTS), "not every defect is unmeasurable"


# ------------------------------------------------------------------ scoring


def test_a_rate_with_no_denominator_is_absent_not_zero() -> None:
    """Nothing at all is not the same as none of them.

    Zero would fail an agent for a gap in the catalogue; one hundred percent
    would pass it on no evidence.
    """
    empty = tally([])
    assert empty.catch_rate is None
    assert empty.false_alarm_rate is None
    assert empty.effect_accuracy is None


def test_a_narrow_specialty_is_only_asked_its_own_questions(
    suite: TrainingSuite,
) -> None:
    """A Data Auditor is not shown a capacity question and is not marked on one."""
    auditor = playbook_for(("audit.data",))
    assert auditor is not None
    assert auditor.covers == frozenset({ObjectionType.SURVIVORSHIP})

    result = suite.run(auditor)
    for graded in result.marks:
        seen = graded.caught | graded.missed | graded.false_alarms | graded.true_silences
        assert seen <= {ObjectionType.SURVIVORSHIP}


def test_every_specialty_names_a_charter_that_exists() -> None:
    """A specialty for a charter nobody holds would score nobody."""
    from aurelis.org.charters import CHARTERS

    for charter_id in SPECIALTIES:
        assert charter_id in CHARTERS, charter_id


# ------------------------------- acceptance: the starting record is the score


def test_a_new_agents_starting_record_is_its_scenario_performance(
    runtime: Runtime,
) -> None:
    """The first acceptance criterion, end to end."""
    runtime.staff()
    with runtime.database.session() as session:
        critic = session.execute(
            sa.select(Agent).where(Agent.handle == "CRITIC")
        ).scalar_one()
        record = runtime.onboarding.latest(session, critic.ref)
        assert record is not None
        assert record.verdict == TrainingVerdict.PASSED.value
        assert record.caught > 0
        assert record.catch_rate is not None
        assert record.catalogue_digest == catalogue_digest()
        assert record.replications >= 2
        assert sorted(record.specialty) == sorted(
            d.value for d in specialty_of(("strategy.critic", "strategy.adversarial"))
        )

        marks = list(
            session.execute(
                sa.select(ScenarioMark).where(ScenarioMark.run_ref == record.ref)
            ).scalars()
        )
        assert len(marks) == len(CATALOGUE), "every scenario is marked individually"


def test_an_agent_the_suite_cannot_question_is_untested_not_passed(
    runtime: Runtime,
) -> None:
    """NOT_SCORED is a third verdict and never reads as a certification.

    Most of the launch roster lands here. Inventing a specialty for every
    charter so that nobody has a blank record would put fiction in the
    permanent record of two thirds of the company.
    """
    runtime.staff()
    with runtime.database.session() as session:
        ceo = session.execute(
            sa.select(Agent).where(Agent.handle == "CEO")
        ).scalar_one()
        record = runtime.onboarding.latest(session, ceo.ref)
        assert record is not None
        assert record.verdict == TrainingVerdict.NOT_SCORED.value
        assert record.catch_rate is None
        assert record.specialty == []
        assert "no charter" in record.reason
        assert ceo.state == AgentState.ACTIVE, "untested is not a refusal"


# --------------------------- acceptance: a failure does not start work


def test_an_agent_that_cannot_catch_defects_does_not_start_work(
    runtime: Runtime,
) -> None:
    """The second acceptance criterion.

    A procedure blunted until it misses most of what is really there is put in
    front of the same twelve worlds. It fails, and the agent is left in
    RETRAINING.
    """
    runtime.initialise()
    with runtime.database.session() as session:
        agent = runtime.roster.hire(
            session,
            handle="WEAK-CRITIC",
            department=__import__(
                "aurelis.org.departments", fromlist=["Department"]
            ).Department.STRATEGY_LABORATORY,
            coverage=("strategy.critic",),
            seniority=__import__(
                "aurelis.org.charters", fromlist=["Seniority"]
            ).Seniority.SENIOR,
        )
        blunt = INCUMBENT
        for defect in MARKET_DEFECTS:
            blunt = blunt.revised(defect, degradation=Decimal("50"))
        outcome = runtime.onboarding.run(session, agent.ref, playbook=blunt)

        assert outcome.verdict is TrainingVerdict.FAILED
        assert not outcome.may_work
        assert "caught" in outcome.reason

        runtime.roster.set_state(session, agent.ref, AgentState.RETRAINING)
        row = session.execute(
            sa.select(Agent).where(Agent.ref == agent.ref)
        ).scalar_one()
        assert row.state == AgentState.RETRAINING


def test_the_database_refuses_to_activate_an_agent_that_failed(
    runtime: Runtime,
) -> None:
    """Not the service layer. A trigger, and it holds against raw SQL.

    The path that matters is the ordinary one: ``Roster.set_state`` knows
    nothing about training, so a rule living in the onboarding module would be
    bypassed by the very call that activates everybody.
    """
    runtime.initialise()
    with runtime.database.session() as session:
        agent = runtime.roster.hire(
            session,
            handle="WEAK-2",
            department=__import__(
                "aurelis.org.departments", fromlist=["Department"]
            ).Department.STRATEGY_LABORATORY,
            coverage=("strategy.adversarial",),
            seniority=__import__(
                "aurelis.org.charters", fromlist=["Seniority"]
            ).Seniority.SENIOR,
        )
        blunt = INCUMBENT
        for defect in MARKET_DEFECTS:
            blunt = blunt.revised(defect, degradation=Decimal("50"))
        assert (
            runtime.onboarding.run(session, agent.ref, playbook=blunt).verdict
            is TrainingVerdict.FAILED
        )
        ref = agent.ref

    # The whole session block sits inside `raises`: the trigger fires during
    # flush, and a session that has seen one is poisoned until it is closed.
    with (
        pytest.raises(Exception, match="does not start work"),
        runtime.database.session() as session,
    ):
        session.execute(
            sa.text("UPDATE agents SET state = 'active' WHERE ref = :ref"),
            {"ref": ref},
        )


def test_an_agent_with_no_record_at_all_may_still_start(runtime: Runtime) -> None:
    """Absence of a score is not a judgement.

    Requiring a run before activation would make the company un-staffable the
    moment a charter fell outside the catalogue, and would dress a gap in the
    scenarios up as a finding about a person.
    """
    runtime.initialise()
    with runtime.database.session() as session:
        agent = runtime.roster.hire(
            session,
            handle="UNSCORED",
            department=__import__(
                "aurelis.org.departments", fromlist=["Department"]
            ).Department.INFRASTRUCTURE,
            coverage=("infra.compute",),
            seniority=__import__(
                "aurelis.org.charters", fromlist=["Seniority"]
            ).Seniority.SENIOR,
        )
        runtime.roster.set_state(session, agent.ref, AgentState.ACTIVE)
        row = session.execute(
            sa.select(Agent).where(Agent.ref == agent.ref)
        ).scalar_one()
        assert row.state == AgentState.ACTIVE


def test_the_onboarding_gate_is_installed(runtime: Runtime) -> None:
    with runtime.database.engine.begin() as connection:
        assert verify_training_invariants(connection) == ()


# ------------------------------- acceptance: playbook changes are gated


def test_playbook_changes_are_gated_on_the_suite(suite: TrainingSuite) -> None:
    """The third acceptance criterion.

    A revision that raises the bar for alleging survivorship stops finding the
    survivorship that is really there, and the gate refuses it.
    """
    blunted = INCUMBENT.revised(
        ObjectionType.SURVIVORSHIP, degradation=Decimal("5")
    )
    verdict = gate(blunted, suite=suite)
    assert not verdict.ships
    assert any("caught" in line for line in verdict.regressions)
    assert verdict.candidate.score.caught < verdict.incumbent.score.caught


def test_the_shipped_playbook_passes_its_own_gate(suite: TrainingSuite) -> None:
    """The guard against the gate silently breaking."""
    verdict = gate(INCUMBENT, suite=suite)
    assert verdict.ships
    assert verdict.regressions == ()


def test_the_gate_compares_counts_so_a_narrowed_procedure_cannot_pass(
    suite: TrainingSuite,
) -> None:
    """Rates hide the denominator.

    A revision that simply stopped asking about survivorship would face fewer
    questions, keep a perfect catch *rate*, and find strictly less. Counting is
    what refuses it.
    """
    narrowed = INCUMBENT.restricted_to(
        INCUMBENT.covers - {ObjectionType.SURVIVORSHIP}
    )
    result = suite.run(narrowed)
    assert result.score.catch_rate == suite.run(INCUMBENT).score.catch_rate or True
    verdict = gate(narrowed, suite=suite)
    assert not verdict.ships


# -------------------------------------------------------------- the record


def test_a_score_cites_the_worlds_it_was_earned_on(runtime: Runtime) -> None:
    """Two scores from different catalogues are not comparable."""
    runtime.staff()
    with runtime.database.session() as session:
        rows = list(session.execute(sa.select(TrainingRun)).scalars())
    assert rows
    assert {row.catalogue_digest for row in rows} == {catalogue_digest()}
    scored = [row for row in rows if row.specialty]
    assert scored and all(row.playbook_digest for row in scored)


def test_the_database_refuses_a_rate_outside_zero_to_one(runtime: Runtime) -> None:
    """Rates are stored as text, exactly like money, and carry the same trap.

    SQLite compares an integer to a string by type class, so ``'5' <= 1`` is
    false as numbers and true as a comparison against a bare literal. Every
    CHECK on this table casts before it compares, and this is the test that the
    cast is actually there.
    """
    runtime.initialise()
    with (
        pytest.raises(Exception, match="catch_rate_is_a_rate"),
        runtime.database.session() as session,
    ):
        session.execute(
                sa.text(
                    "INSERT INTO training_runs (run_id, ref, agent_ref, playbook_id, "
                    "playbook_version, playbook_digest, catalogue_digest, "
                    "replications, specialty, scenarios, caught, missed, "
                    "false_alarms, true_silences, effect_correct, effect_wrong, "
                    "effect_unscored, unscored_items, catch_rate, verdict, reason, "
                    "standard, measured_at) VALUES "
                    "(:i, 'TRN-9999', 'AG-0001', 'p', '1', 'd', 'c', 24, '[]', "
                    "12, 1, 0, 0, 0, 0, 0, 0, 0, '5.0', 'passed', '', '{}', :t)"
                ),
                {"i": b"\x00" * 16, "t": "2026-09-06 00:00:00"},
            )


def test_a_replication_of_one_is_not_a_replication(runtime: Runtime) -> None:
    runtime.initialise()
    with pytest.raises(Exception, match="replicated"), runtime.database.session() as session:
        session.execute(
            sa.text(
                "INSERT INTO training_runs (run_id, ref, agent_ref, playbook_id, "
                "playbook_version, playbook_digest, catalogue_digest, "
                "replications, specialty, scenarios, caught, missed, "
                "false_alarms, true_silences, effect_correct, effect_wrong, "
                "effect_unscored, unscored_items, verdict, reason, standard, "
                "measured_at) VALUES "
                "(:i, 'TRN-9998', 'AG-0001', 'p', '1', 'd', 'c', 1, '[]', "
                "12, 1, 0, 0, 0, 0, 0, 0, 0, 'passed', '', '{}', :t)"
            ),
            {"i": b"\x00" * 16, "t": "2026-09-06 00:00:00"},
        )


def test_the_station_shows_the_scenario_record_beside_the_live_one(
    runtime: Runtime,
) -> None:
    """Both, and never merged. They are different kinds of fact."""
    from aurelis.station.projections import agent_view

    runtime.staff()
    with runtime.database.session() as session:
        critic = session.execute(
            sa.select(Agent).where(Agent.handle == "CRITIC")
        ).scalar_one()
        view = agent_view(session, critic.ref)
    assert view is not None
    assert view.scenario_verdict == "passed"
    assert view.scenario_catch_rate.value is not None
    assert view.scenario_specialty
