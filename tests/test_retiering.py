"""M19 — the company pays for its own shape, and changes it on the evidence.

Every charter has declared a model tier since M1. Until M17 gave that field
something downstream of it, the number cost nothing and meant nothing. Now an
agent routes at the **highest** tier of the charters it holds, because it must
be capable of its most demanding role — so a generalist holding one expensive
charter runs all its work on that model.

Twenty-five charters at the launch roster. That is a fact about the company's
own shape, measured from its own record, and M11 already had the machinery to
act on it: triggers, preregistered predictions, measured effects. These tests
are the two halves joined.

The acceptance is not "the company got better". It is that the company
**measured** how much better, and reported the part the change did not fix.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from aurelis.agents.tables import Agent, AgentCoverage, AgentState
from aurelis.core.enums import ModelTier
from aurelis.org.charters import CHARTERS
from aurelis.org.registry import resolve_authority
from aurelis.orgdev.detection import TRIGGERS, scan
from aurelis.orgdev.metrics import METRICS, agent_metrics
from aurelis.orgdev.retiering import cheaper_charters, run_retiering
from aurelis.orgdev.states import EffectVerdict, OrgChangeKind, TriggerKind
from aurelis.orgdev.tables import OrgChange
from aurelis.runtime import Runtime

_LADDER = (ModelTier.NONE, ModelTier.LOW, ModelTier.MID, ModelTier.HIGH)


@pytest.fixture
def company(settings, clock) -> Runtime:  # type: ignore[no-untyped-def]
    built = Runtime.build(settings, clock=clock)
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


# ------------------------------------------------------------- the metric


def test_the_company_can_predict_what_its_shape_costs() -> None:
    """A change may only predict a metric the company can compute. Adding one
    is how it becomes able to make a new kind of prediction about itself."""
    assert "overtiered_charters" in METRICS
    assert "model_tokens" in METRICS


def test_an_agent_is_overtiered_by_what_it_holds_below_its_own_tier(
    company: Runtime,
) -> None:
    """The number is exactly derivable from coverage and the charter registry,
    so it can be checked here rather than trusted."""
    with company.database.session() as session:
        audit = company.roster.by_handle(session, "AUDIT")
        reading = agent_metrics(session, audit.ref).get("overtiered_charters")
        held = [str(c) for c in audit.coverage]

    top = resolve_authority(tuple(held)).tier
    expected = sum(
        1
        for charter_id in held
        if CHARTERS[charter_id].tier is not ModelTier.NONE
        and _LADDER.index(CHARTERS[charter_id].tier) < _LADDER.index(top)
    )
    assert reading.value == expected
    assert expected > 0, "AUDIT spans low, mid and high"
    assert "routes at high" in reading.detail


def test_work_that_calls_no_model_is_not_counted_as_overtiered(
    company: Runtime,
) -> None:
    """``NONE`` means the work is deterministic and calls no model at all, so
    holding it costs nothing however the agent routes. Counting it would
    inflate the case for a split with work that was never going to be billed.
    """
    with company.database.session() as session:
        gov = company.roster.by_handle(session, "GOV")
        moved = cheaper_charters(session, gov.ref)

    none_tier = {cid for cid in gov.coverage if CHARTERS[cid].tier is ModelTier.NONE}
    assert none_tier, "GOV holds every NONE-tier charter"
    assert not none_tier & set(moved)


def test_a_specialist_is_not_overtiered(company: Runtime) -> None:
    """Zero is a real reading here, not an absence: an agent holding one
    charter routes at exactly that charter's tier."""
    with company.database.session() as session:
        ceo = company.roster.by_handle(session, "CEO")
        assert len(ceo.coverage) == 1
        assert agent_metrics(session, ceo.ref).value("overtiered_charters") == 0
        assert cheaper_charters(session, ceo.ref) == ()


# ------------------------------------------------------------ the trigger


def test_the_trigger_is_declared_rather_than_chosen(company: Runtime) -> None:
    """A threshold picked after the reading is a justification, not a
    trigger."""
    trigger = next(t for t in TRIGGERS if t.kind is TriggerKind.TIER_WASTE)
    assert trigger.metric == "overtiered_charters"
    assert trigger.comparison == "gte"
    assert trigger.proposes is OrgChangeKind.FISSION

    with company.database.session() as session:
        hits = [h for h in scan(session) if h.trigger.kind is TriggerKind.TIER_WASTE]
    assert hits, "the launch roster fires this on itself"
    assert all((hit.reading.value or 0) >= trigger.threshold for hit in hits)


def test_the_subject_is_scanned_for_rather_than_named(company: Runtime) -> None:
    """A demonstration that picked its subject would be a script pretending to
    be a measurement."""
    with company.database.session() as session:
        hits = [h for h in scan(session) if h.trigger.kind is TriggerKind.TIER_WASTE]
        worst = max(hits, key=lambda h: h.reading.value or 0)

    outcome = run_retiering(company)
    assert outcome.subject == worst.subject
    assert outcome.subject_handle == worst.handle


# ------------------------------------------------- the change, end to end


def test_the_company_reorganises_itself_and_measures_the_effect(
    company: Runtime,
) -> None:
    """The acceptance. Proposed on a reading, hashed before the room saw it,
    applied through the same handover as every other change, and measured
    against the prediction it was locked to."""
    outcome = run_retiering(company)

    assert outcome.subject_before > 0
    assert outcome.subject_after == 0, "everything written cheaper was moved"
    assert outcome.verdict == EffectVerdict.IMPROVED.value
    assert outcome.prediction_held
    assert outcome.onboarding == "passed", "the new agent is scored before it works"

    with company.database.session() as session:
        change = session.execute(
            sa.select(OrgChange).where(OrgChange.ref == outcome.change_ref)
        ).scalar_one()
    assert change.locked_at is not None
    assert change.meeting_ref == outcome.meeting_ref
    assert change.predicted_metric == "overtiered_charters"
    assert change.kind == OrgChangeKind.FISSION.value


def test_one_split_does_not_reach_zero_and_the_report_says_so(
    company: Runtime,
) -> None:
    """The honest half.

    Moving everything below the top tier off an agent leaves the *new* agent
    holding a spread of its own, so it is overtiered in turn. The company total
    therefore improves by less than what moved, and a report that showed only
    the subject's number would be claiming a fix it did not make.
    """
    outcome = run_retiering(company)

    assert outcome.company_after < outcome.company_before
    assert outcome.company_improved < len(outcome.moved), (
        "the new agent inherited a spread, so not every moved charter is fixed"
    )

    with company.database.session() as session:
        new_agent = agent_metrics(session, outcome.new_agent)
    assert new_agent.value("overtiered_charters") > 0
    assert outcome.as_payload()["company_after"] == outcome.company_after


def test_coverage_moves_and_is_never_dropped(company: Runtime) -> None:
    """The guarantee ADR-0003 rests on, exercised through a new kind of
    change: every charter still has a holder afterwards."""
    with company.database.session() as session:
        before = {
            str(row)
            for row in session.execute(sa.select(AgentCoverage.charter_id)).scalars()
        }

    outcome = run_retiering(company)

    with company.database.session() as session:
        after = {
            str(row)
            for row in session.execute(sa.select(AgentCoverage.charter_id)).scalars()
        }
        moved_to = {
            str(row)
            for row in session.execute(
                sa.select(AgentCoverage.charter_id).where(
                    AgentCoverage.agent_ref == outcome.new_agent
                )
            ).scalars()
        }
    assert before == after, "a split moves coverage, it does not create or drop it"
    assert moved_to == set(outcome.moved)


def test_the_report_does_not_claim_a_saving_it_has_not_observed(
    company: Runtime,
) -> None:
    """Every model call in this repository reports zero marginal cost under a
    subscription. The rate table says what the tier gap is worth; the company
    does not print a number it never measured."""
    outcome = run_retiering(company)
    payload = outcome.as_payload()

    assert "structural" in payload["caveat"]
    assert "no money saved has been observed" in payload["caveat"]
    assert "per Mtok" in outcome.rate_gap
    assert "subscription reports no marginal cost" in outcome.rate_gap


def test_an_agent_may_not_propose_a_change_to_its_own_record(
    company: Runtime,
) -> None:
    """Self-modification would make the growth mechanism unauditable."""
    outcome = run_retiering(company)
    with company.database.session() as session:
        change = session.execute(
            sa.select(OrgChange).where(OrgChange.ref == outcome.change_ref)
        ).scalar_one()
    assert change.proposed_by != change.subject_agent


def test_a_company_with_nothing_to_retier_says_so(company: Runtime) -> None:
    """Running out of things to fix is a result, not a failure.

    Driven here by splitting until the trigger stops firing, which is also the
    honest answer to "how many of these does the launch roster need?"
    """
    from aurelis.core.errors import IntegrityViolation

    splits = 0
    while splits < 12:
        try:
            run_retiering(company, new_handle=f"SPLIT-{splits}")
        except IntegrityViolation as error:
            assert "Nothing to reorganise" in str(error)
            break
        splits += 1
    else:  # pragma: no cover - the roster is finite
        pytest.fail("the trigger never stopped firing")

    assert splits >= 1
    with company.database.session() as session:
        remaining = [
            h for h in scan(session) if h.trigger.kind is TriggerKind.TIER_WASTE
        ]
        active = list(
            session.execute(
                sa.select(Agent).where(
                    Agent.state.notin_((AgentState.RETIRED, AgentState.SUSPENDED))
                )
            ).scalars()
        )
    assert not remaining, "no agent still holds three charters below its tier"
    assert len(active) > 17, "the company grew to get there"
