"""M16 and M26 — a search budget declared first, and the number that survives it.

M15 authored once and stopped, and said why: a revision loop is where authoring
turns into mining, and the stopping rule had to be designed before the loop
was. These tests are the loop with the rule attached — now over rules the
agent writes rather than menu picks.

Two acceptances, both negative. The campaign finds a rule that beats holding
the asset — revising moved the number — and the correction says the number is
still noise. And the correction itself had to be tightened the day the menu
went: with a declared width of four rather than ninety-six, a positive surplus
on a *fixture* was a coin toss, so a surplus must now clear the estimator's own
noise as well.

**What sits behind the seat is a deterministic stand-in, not a model**, and
every desk runs on fixtures.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.authoring.attempt import family_for
from aurelis.authoring.campaign import BUDGET, CRITERION, declared_width, run_campaign
from aurelis.authoring.invariants import AUTHORING_TRIGGERS, verify_authoring_invariants
from aurelis.authoring.revision import REVISION_FORM, revision_material
from aurelis.authoring.selection import (
    MARGIN_Z,
    check_selection,
    expected_best_of,
    standard_error_from,
)
from aurelis.authoring.standin import scripted_author
from aurelis.authoring.tables import AuthoringAttempt, Campaign
from aurelis.platform.llm.providers import MockProvider
from aurelis.rules import parse
from aurelis.runtime import Runtime
from aurelis.strategy.states import Origin

_SPAN = Decimal("0.25")


@pytest.fixture
def company(settings, clock) -> Runtime:  # type: ignore[no-untyped-def]
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=scripted_author))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


# ------------------------------------------------------- the correction itself


def test_searching_wider_raises_the_bar() -> None:
    error = Decimal("0.02")
    bars = [expected_best_of(n, error) for n in (2, 6, 72, 96, 360)]
    assert bars == sorted(bars)
    assert all(a < b for a, b in zip(bars, bars[1:], strict=False))


def test_a_single_trial_has_nothing_to_correct() -> None:
    assert expected_best_of(1, Decimal("0.02")) == 0
    with pytest.raises(ValueError, match="at least one trial"):
        expected_best_of(0, Decimal("0.02"))


def test_a_run_with_no_interval_cannot_be_corrected() -> None:
    assert standard_error_from(None, Decimal("1")) is None
    assert standard_error_from(Decimal("1"), Decimal("1")) is None
    check = check_selection(observed=Decimal("2"), low=None, high=None, n_trials=96)
    assert not check.measurable
    assert not check.survives
    assert check.margin is None
    assert "no interval" in check.describe()


def test_a_positive_surplus_inside_the_noise_does_not_survive() -> None:
    """Under the null the best of n lands above its own expectation about half
    the time. A surplus smaller than the estimator's noise is that coin toss,
    and it was the first four-rule campaign on a fixture."""
    error = Decimal("0.02")
    expected = expected_best_of(4, error)
    low = Decimal("0.05") - Decimal("1.96") * error
    high = Decimal("0.05") + Decimal("1.96") * error
    inside = check_selection(observed=expected + Decimal("0.005"), low=low, high=high, n_trials=4)
    assert inside.surplus > 0 and not inside.survives
    assert inside.margin == (MARGIN_Z * inside.standard_error).quantize(Decimal("0.00000001"))
    beyond = check_selection(observed=expected + Decimal("0.05"), low=low, high=high, n_trials=4)
    assert beyond.survives
    assert "margin" in inside.describe()
    assert inside.as_payload()["margin"] is not None


def test_the_correction_says_what_it_assumes() -> None:
    check = check_selection(
        observed=Decimal("0.05"), low=Decimal("0.01"), high=Decimal("0.09"), n_trials=96
    )
    assert "conservative" in check.as_payload()["assumption"]
    assert check.standard_error is not None


# ----------------------------------------------------------- the revision seat


def test_the_revision_is_shown_its_own_result_and_the_first_attempt_is_not() -> None:
    """A rule chosen after seeing an answer is a selection -- except inside a
    declared campaign, where the width was declared first and the final
    number pays for it."""
    from aurelis.authoring.author import Citations, material_for

    base = material_for("crypto", bars=2190, citations=Citations(task_ref="TSK-0001"))
    assert "what_it_measured" not in base
    material = revision_material(
        base,
        program=parse("ret(168) > 0.02 -> long"),
        metrics={"sharpe": "0.01"},
        baselines={"always_long": "0.24"},
        attempt=2,
        budget=5,
        already_tried={"ret(168) > 0.02 -> long": "sharpe 0.01"},
    )
    assert material["your_previous_rule"] == "ret(168) > 0.02 -> long"
    assert material["what_it_measured"] == {"sharpe": "0.01"}
    assert material["rules_already_measured"] == {"ret(168) > 0.02 -> long": "sharpe 0.01"}
    assert material["campaign"]["this attempt"] == 2
    assert "already measured" in REVISION_FORM


def test_revision_material_may_not_overwrite_the_structure() -> None:
    with pytest.raises(ValueError, match="overwrite"):
        revision_material(
            {"campaign": {}},
            program=parse("ret(6) > 0 -> long"),
            metrics={},
            baselines={},
            attempt=2,
            budget=3,
        )


# ------------------------------------------------------- the budget, frozen


def test_the_plan_is_locked_before_the_first_rule_exists(company: Runtime) -> None:
    outcome = run_campaign(company, span=_SPAN, budget=3)
    with company.database.session() as session:
        row = session.execute(
            sa.select(Campaign).where(Campaign.ref == outcome.campaign_ref)
        ).scalar_one()
        first = (
            session.execute(
                sa.select(AuthoringAttempt)
                .where(AuthoringAttempt.campaign_ref == outcome.campaign_ref)
                .order_by(AuthoringAttempt.ref)
            )
            .scalars()
            .first()
        )
    assert row.locked_at is not None and row.plan_digest
    assert row.criterion == CRITERION
    assert row.locked_at <= first.created_at
    assert row.declared_width == declared_width(3) == 3


def test_a_campaign_budget_cannot_be_raised_once_it_has_run(company: Runtime) -> None:
    with company.database.engine.connect() as connection:
        assert verify_authoring_invariants(connection) == ()
    assert AUTHORING_TRIGGERS
    outcome = run_campaign(company, span=_SPAN, budget=2)
    with company.database.session() as session:
        try:
            session.execute(
                sa.update(Campaign)
                .where(Campaign.ref == outcome.campaign_ref)
                .values(budget=50, declared_width=5000)
            )
            session.flush()
        except Exception as error:  # noqa: BLE001 - the database raises, not us
            session.rollback()
            message = str(error)
        else:  # pragma: no cover - reaching this is the failure
            message = ""
    assert "frozen" in message


def test_the_declared_width_is_the_number_of_rules_and_the_record_agrees(
    company: Runtime,
) -> None:
    """One rule, one cell. The family's summed declared cells equal the width
    the campaign wrote down before it started."""
    outcome = run_campaign(company, span=_SPAN, budget=BUDGET)
    with company.database.session() as session:
        counted = company.research.trial_count(session, family_for("crypto"))
    assert outcome.width == declared_width(BUDGET) == BUDGET
    assert counted == len(outcome.attempts)
    assert all(attempt.declared_cells == 1 for attempt in outcome.attempts)


def test_a_campaign_that_cannot_revise_stops_and_says_so(company: Runtime) -> None:
    """The stand-in's policy has five steps. Asked for more, it declines, and
    the campaign records a refusal rather than inventing a rule to fill the
    budget."""
    outcome = run_campaign(company, span=_SPAN, budget=9)
    assert len(outcome.attempts) < 9
    assert outcome.refusals
    assert "declined" in outcome.refusals[-1]
    with company.database.session() as session:
        row = session.execute(
            sa.select(Campaign).where(Campaign.ref == outcome.campaign_ref)
        ).scalar_one()
    assert row.refusals == len(outcome.refusals)
    assert row.exhausted is False


def test_a_campaign_refuses_to_re_measure_a_rule_it_has_already_tried(
    settings,
    clock,  # type: ignore[no-untyped-def]
) -> None:
    def reverting(request):  # type: ignore[no-untyped-def]
        prompt = request.messages[-1].content
        if "Your rule was measured" in prompt:
            if "ret(72)" in prompt.split("Rules Already Measured")[-1]:
                return "RULE:\nret(168) > 0.02 -> long\nRATIONALE: back to the slowest window."
            return "RULE:\nret(72) > 0.02 -> long\nRATIONALE: a shorter window trades sooner."
        return scripted_author(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=reverting))
    built.initialise()
    built.staff()
    try:
        outcome = run_campaign(built, span=Decimal("0.1"), budget=4)
    finally:
        built.close()
    assert len(outcome.attempts) == 2, "it stopped when the third would repeat"
    assert "already measured" in outcome.refusals[-1]
    digests = [item.authored.program.digest for item in outcome.attempts]
    assert len(set(digests)) == len(digests)


# --------------------------------------------------------- the honest headline


def test_the_campaign_finds_something_and_the_correction_takes_it_away(
    company: Runtime,
) -> None:
    """Revising moves the number: the campaign reaches a rule that beats
    holding the asset. The correction then says that number is inside what
    searching this wide returns from noise, once the estimator's own noise is
    charged. Reporting the first half without the second is precisely how a
    company convinces itself it has found an edge."""
    outcome = run_campaign(company, span=_SPAN, budget=BUDGET)
    best = outcome.best
    assert best is not None
    assert best.sharpe > outcome.attempts[0].sharpe, "revising moved the number"
    assert outcome.beat_baselines, "and the best rule beat holding the asset"
    assert outcome.selection.measurable
    assert not outcome.selection.survives
    assert outcome.selection.margin is not None
    assert outcome.selection.surplus <= outcome.selection.margin
    assert "does NOT clear" in outcome.selection.describe()
    with company.database.session() as session:
        row = session.execute(
            sa.select(Campaign).where(Campaign.ref == outcome.campaign_ref)
        ).scalar_one()
    assert row.survives_selection is False
    assert row.best_attempt_ref == best.attempt_ref


def test_revising_is_not_the_same_as_improving(company: Runtime) -> None:
    outcome = run_campaign(company, span=_SPAN, budget=BUDGET)
    sharpes = [attempt.sharpe for attempt in outcome.attempts]
    assert sharpes != sorted(sharpes), "the walk does not climb"
    assert not outcome.improved


def test_a_revision_is_recorded_as_refinement_not_invention(company: Runtime) -> None:
    outcome = run_campaign(company, span=_SPAN, budget=3)
    first, *rest = outcome.attempts
    assert first.authored.origin is Origin.INVENTED
    assert all(item.authored.origin is Origin.REFINED for item in rest)
    for item in rest:
        assert item.authored.origin_ref.startswith("CMP-")
        assert item.authored.novelty is not None
        assert item.authored.novelty.by_origin.get(Origin.REFINED.value, 0) >= 1


def test_the_lineage_says_how_the_company_got_here(company: Runtime) -> None:
    outcome = run_campaign(company, span=_SPAN, budget=4)
    last = outcome.attempts[-1]
    with company.database.session() as session:
        ancestry = company.synthesis.ancestry(session, last.authored.version_ref)
    assert len(ancestry) == len(outcome.attempts)
    assert ancestry[-1] == last.authored.version_ref
    assert ancestry[0] == outcome.attempts[0].authored.version_ref


def test_the_campaign_report_carries_the_correction_and_the_caveat(company: Runtime) -> None:
    outcome = run_campaign(company, span=_SPAN, budget=2)
    payload = outcome.as_payload()
    assert payload["criterion"] == CRITERION
    assert payload["selection"]["survives"] is False
    assert payload["declared_width"] == declared_width(2)
    assert "stand-in, not a model" in payload["caveat"]
    assert "conservative" in payload["selection"]["assumption"]


def test_the_workshop_shows_the_surplus_next_to_the_headline(company: Runtime) -> None:
    from aurelis.station.pages import workshop_page

    outcome = run_campaign(company, span=_SPAN, budget=3)
    with company.database.session() as session:
        html = workshop_page(session)
    assert "Campaigns" in html
    assert outcome.campaign_ref in html
    assert str(outcome.selection.observed) in html
    assert str(outcome.selection.expected_by_chance) in html
