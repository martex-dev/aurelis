"""M16 — a search budget declared first, and the number that survives it.

M15 authored once and stopped, and said why: a revision loop is where authoring
turns into mining, and the stopping rule had to be designed before the loop
was. These tests are the loop with the rule attached.

The acceptance is again a negative one, and it is sharper than M15's. The
campaign here **does** find a design that beats holding the asset — revising
moved the number — and the correction says the number is still less than what
searching that wide returns from noise alone. A system that reported the first
half without the second would be a false-discovery machine with a lineage
graph.

**What sits behind the seat is a deterministic stand-in, not a model**, and
every desk runs on fixtures.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.authoring.attempt import family_for
from aurelis.authoring.campaign import (
    BUDGET,
    CRITERION,
    declared_width,
    run_campaign,
)
from aurelis.authoring.design import FAMILY, Design, enumerate_designs, space_size
from aurelis.authoring.invariants import (
    AUTHORING_TRIGGERS,
    verify_authoring_invariants,
)
from aurelis.authoring.revision import (
    REVISABLE,
    revisable_slots,
    revised,
    revision_material,
    revision_space,
    what_to_change_question,
    which_slot_question,
)
from aurelis.authoring.selection import (
    check_selection,
    expected_best_of,
    standard_error_from,
)
from aurelis.authoring.standin import scripted_author
from aurelis.authoring.tables import AuthoringAttempt, Campaign
from aurelis.platform.llm.providers import MockProvider
from aurelis.runtime import Runtime
from aurelis.strategy.states import Origin

_SPAN = Decimal("0.25")


@pytest.fixture
def company(settings, clock) -> Runtime:  # type: ignore[no-untyped-def]
    built = Runtime.build(
        settings, clock=clock, provider=MockProvider(responder=scripted_author)
    )
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


# ------------------------------------------------------- the correction itself


def test_searching_wider_raises_the_bar() -> None:
    """The whole reason a budget has to be declared rather than discovered.

    Every extra design a company lets itself try raises what it must beat,
    because the best of more draws from noise is larger.
    """
    error = Decimal("0.02")
    bars = [expected_best_of(n, error) for n in (2, 6, 72, 96, 360)]
    assert bars == sorted(bars)
    assert all(a < b for a, b in zip(bars, bars[1:], strict=False))


def test_a_single_trial_has_nothing_to_correct() -> None:
    """One draw has no maximum to inflate. Zero, not a small positive number
    — a correction applied to an uncorrectable case would be superstition."""
    assert expected_best_of(1, Decimal("0.02")) == 0
    with pytest.raises(ValueError, match="at least one trial"):
        expected_best_of(0, Decimal("0.02"))


def test_a_run_with_no_interval_cannot_be_corrected() -> None:
    """``None`` propagates rather than becoming an assumed standard error.

    A correction computed from a number nobody measured is exactly the kind of
    figure this company refuses to put on a report.
    """
    assert standard_error_from(None, Decimal("1")) is None
    assert standard_error_from(Decimal("1"), Decimal("1")) is None

    check = check_selection(observed=Decimal("2"), low=None, high=None, n_trials=96)
    assert not check.measurable
    assert not check.survives
    assert "no interval" in check.describe()


def test_the_correction_says_what_it_assumes() -> None:
    """Independence and normality are both false here, and the direction of the
    error is stated: correlated designs make the true bar lower, so the
    correction is conservative and may call a real edge nothing."""
    check = check_selection(
        observed=Decimal("0.05"),
        low=Decimal("0.01"),
        high=Decimal("0.09"),
        n_trials=96,
    )
    assert "conservative" in check.as_payload()["assumption"]
    assert check.standard_error is not None


# ----------------------------------------------------------- the revision seat


def test_a_revision_changes_exactly_one_thing() -> None:
    """A revision that rewrote every choice would be a new design wearing a
    lineage, and the ancestry chain would say something false."""
    design = enumerate_designs()[0]
    slot = revisable_slots(design.family)[0]
    other = next(c.key for c in slot.choices if c.key != design.get(slot.name))

    after = revised(design, slot.name, other)
    changed = [
        name
        for name, _ in design.picks
        if design.get(name) != after.get(name)
    ]
    assert changed == [slot.name]
    assert after.family == design.family


def test_the_family_is_not_revisable() -> None:
    """A different kind of edge is a different idea, not a revision of this
    one — and the equal branch widths that let a campaign declare its cells in
    advance depend on it."""
    design = enumerate_designs()[0]
    with pytest.raises(ValueError, match="different idea"):
        revised(design, FAMILY, "rotation")

    assert all(slot.name != FAMILY for slot in revisable_slots("momentum"))
    for family in ("momentum", "mean_reversion", "rotation"):
        one = next(d for d in enumerate_designs() if d.family == family)
        assert revision_space(one) == REVISABLE


def test_a_revision_may_not_be_a_no_op() -> None:
    """It would still cost a cell and still produce a justification."""
    design = enumerate_designs()[0]
    with pytest.raises(ValueError, match="already"):
        revised(design, "lookback", design.get("lookback"))

    slot = next(s for s in revisable_slots(design.family) if s.name == "lookback")
    offered = {c.key for c in what_to_change_question(design, slot).options}
    assert design.get("lookback") not in offered


def test_the_revision_is_shown_its_own_result_and_the_first_attempt_is_not(
    company: Runtime,
) -> None:
    """The trade the milestone rests on: a design chosen after seeing an
    answer is a selection, and a declared budget is what buys the right to
    make one."""
    from aurelis.authoring.author import Citations, material_for

    structural = material_for(
        "crypto", bars=600, citations=Citations(task_ref="TSK-0001")
    )
    assert "what_it_measured" not in structural

    design = enumerate_designs()[0]
    revising = revision_material(
        structural,
        design=design,
        metrics={"sharpe": "0.01"},
        baselines={"always_long": "0.24"},
        attempt=2,
        budget=BUDGET,
    )
    assert revising["what_it_measured"] == {"sharpe": "0.01"}
    assert revising["campaign"]["attempts in the campaign"] == BUDGET
    # And the structural half is unchanged, so which of the two the agent
    # responded to is answerable.
    for section, payload in structural.items():
        assert revising[section] == payload


def test_the_slot_question_shows_what_is_currently_in_place() -> None:
    """An agent asked to change something it cannot see is guessing."""
    design = Design(
        (
            (FAMILY, "momentum"),
            ("lookback", "one_week"),
            ("threshold", "two_percent"),
            ("direction", "long_only"),
        )
    )
    rendered = which_slot_question(design).render()
    assert "currently one_week" in rendered
    assert "currently two_percent" in rendered
    assert FAMILY not in {c.key for c in which_slot_question(design).options}


# ----------------------------------------------------------- the budget is real


def test_the_plan_is_locked_before_the_first_design_exists(
    company: Runtime,
) -> None:
    outcome = run_campaign(company, span=_SPAN, budget=3)
    with company.database.session() as session:
        row = session.execute(
            sa.select(Campaign).where(Campaign.ref == outcome.campaign_ref)
        ).scalar_one()
        first = session.execute(
            sa.select(AuthoringAttempt)
            .where(AuthoringAttempt.campaign_ref == outcome.campaign_ref)
            .order_by(AuthoringAttempt.ref)
        ).scalars().first()

    assert row.locked_at is not None
    assert row.plan_digest
    assert row.criterion == CRITERION
    assert row.locked_at <= first.created_at
    assert row.declared_width == declared_width(3) == space_size() + 2 * REVISABLE


def test_a_campaign_budget_cannot_be_raised_once_it_has_run(
    company: Runtime,
) -> None:
    """Enforced by the database, not by the campaign module.

    A budget raised after seeing the results is not a budget, it is a
    description of what happened — and application code is one console session
    away from being bypassed.
    """
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
    with company.database.session() as session:
        row = session.execute(
            sa.select(Campaign).where(Campaign.ref == outcome.campaign_ref)
        ).scalar_one()
    assert row.budget == 2


def test_the_declared_width_is_what_the_record_counts(company: Runtime) -> None:
    """The plan and the ledger agree, and the agreement is checked rather than
    asserted in a report: the family's summed declared cells equal the width
    the campaign wrote down before it started."""
    outcome = run_campaign(company, span=_SPAN, budget=BUDGET)
    with company.database.session() as session:
        counted = company.research.trial_count(session, family_for("crypto"))

    assert outcome.width == declared_width(BUDGET) == 96
    assert counted == outcome.width
    cells = [attempt.declared_cells for attempt in outcome.attempts]
    assert cells == [space_size(), *([REVISABLE] * (len(cells) - 1))]


def test_a_campaign_that_cannot_revise_stops_and_says_so(
    company: Runtime,
) -> None:
    """The stand-in's policy has six steps in it. Asked for more, it abstains,
    and the campaign records a refusal rather than inventing a change to fill
    the budget."""
    outcome = run_campaign(company, span=_SPAN, budget=9)
    assert len(outcome.attempts) < 9
    assert outcome.refusals
    assert "abstained" in outcome.refusals[-1]

    with company.database.session() as session:
        row = session.execute(
            sa.select(Campaign).where(Campaign.ref == outcome.campaign_ref)
        ).scalar_one()
    assert row.refusals == len(outcome.refusals)
    assert row.exhausted is False, "it stopped early, and the row says so"


# --------------------------------------------------------- the honest headline


def test_the_campaign_finds_something_and_the_correction_takes_it_away(
    company: Runtime,
) -> None:
    """The acceptance, and it is the whole milestone in one test.

    Revising moves the number: the campaign reaches a design that beats holding
    the asset, which M15's single attempt did not. The correction then says
    that number is still below what searching this wide returns from noise
    alone. Reporting the first half without the second is precisely how a
    company convinces itself it has found an edge.
    """
    outcome = run_campaign(company, span=_SPAN, budget=BUDGET)

    best = outcome.best
    assert best is not None
    assert best.sharpe > outcome.attempts[0].sharpe, "revising moved the number"
    assert outcome.beat_baselines, "and the best design beat holding the asset"

    assert outcome.selection.measurable
    assert outcome.selection.expected_by_chance > best.sharpe
    assert outcome.selection.surplus < 0
    assert not outcome.selection.survives
    assert "does NOT clear" in outcome.selection.describe()

    with company.database.session() as session:
        row = session.execute(
            sa.select(Campaign).where(Campaign.ref == outcome.campaign_ref)
        ).scalar_one()
    assert row.survives_selection is False
    assert row.best_attempt_ref == best.attempt_ref
    assert Decimal(row.surplus) == outcome.selection.surplus


def test_revising_is_not_the_same_as_improving(company: Runtime) -> None:
    """Four of the five attempts are worse than the one before them. A campaign
    that reported only its maximum would read as a search converging on
    something; it is a walk, and one point on it happened to be high."""
    outcome = run_campaign(company, span=_SPAN, budget=BUDGET)
    sharpes = [attempt.sharpe for attempt in outcome.attempts]
    assert sharpes != sorted(sharpes), "the walk does not climb"
    assert not outcome.improved, "the last attempt is not the best one"


def test_a_revision_is_recorded_as_refinement_not_invention(
    company: Runtime,
) -> None:
    """Otherwise the company could inflate what it created by changing one
    number five times."""
    outcome = run_campaign(company, span=_SPAN, budget=3)
    first, *rest = outcome.attempts

    assert first.authored.origin is Origin.INVENTED
    assert all(item.authored.origin is Origin.REFINED for item in rest)
    for item in rest:
        assert item.authored.origin_ref.startswith("CMP-"), "it cites the piece it replaced"
        assert item.authored.novelty is not None
        assert item.authored.novelty.by_origin.get(Origin.REFINED.value, 0) >= 1


def test_the_lineage_says_how_the_company_got_here(company: Runtime) -> None:
    """Every revision is a new version superseding the last, never an edit: an
    edited version is a list of things that are no longer true."""
    outcome = run_campaign(company, span=_SPAN, budget=4)
    last = outcome.attempts[-1]

    with company.database.session() as session:
        ancestry = company.synthesis.ancestry(session, last.authored.version_ref)
    assert len(ancestry) == len(outcome.attempts)
    assert ancestry[-1] == last.authored.version_ref
    assert ancestry[0] == outcome.attempts[0].authored.version_ref
    assert len(set(ancestry)) == len(ancestry)


def test_the_campaign_report_carries_the_correction_and_the_caveat(
    company: Runtime,
) -> None:
    outcome = run_campaign(company, span=_SPAN, budget=2)
    payload = outcome.as_payload()

    assert payload["criterion"] == CRITERION
    assert payload["selection"]["survives"] is False
    assert payload["declared_width"] == declared_width(2)
    assert "stand-in, not a model" in payload["caveat"]
    assert "conservative" in payload["selection"]["assumption"]


def test_the_workshop_shows_the_surplus_next_to_the_headline(
    company: Runtime,
) -> None:
    """Mission Control never shows the best number without the correction.

    The charter is explicit that the station must never be arranged to look
    successful, and a campaign row showing only its maximum would be exactly
    that — a discovery, rendered.
    """
    from aurelis.station.pages import workshop_page

    outcome = run_campaign(company, span=_SPAN, budget=3)
    with company.database.session() as session:
        html = workshop_page(session)

    assert "Campaigns" in html
    assert outcome.campaign_ref in html
    assert str(outcome.selection.observed) in html
    assert str(outcome.selection.expected_by_chance) in html
    assert f"<b>{outcome.selection.surplus}</b>" in html, (
        "a negative surplus is emphasised, not tucked into a column"
    )
    assert "SURVIVED THE SEARCH" in html, "the panel counts campaigns that cleared it"
