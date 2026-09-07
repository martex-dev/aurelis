"""M15 — an agent authors a strategy, and the search it did is on the record.

M8 built the surface an agent would author through and said so in its own
docstring; until now the pieces were written by hand in a fixture. These tests
are the agent doing it, plus the guards that stop "an agent created a strategy"
from quietly becoming untrue.

The acceptance is deliberately not "the strategy worked". It is that the
company authored one, declared how wide a space it chose from, measured it
against criteria locked first, and **reported that it did not beat holding the
asset** — which is the outcome the charter says the architecture must make
reachable.

**What sits behind the seat here is not a model.** Every model call in this
repository runs against the mock provider, so a deterministic stand-in supplies
the answers. What is tested is the machinery.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aurelis.agents.decide import NOTHING
from aurelis.agents.interpret import UnsourcedFigures
from aurelis.authoring.attempt import CAVEAT, run_authoring
from aurelis.authoring.author import (
    MATERIAL_SECTIONS,
    WEAKNESSES,
    AuthoringRefused,
    Citations,
    StrategyAuthor,
    material_for,
    origin_question,
)
from aurelis.authoring.design import (
    BASELINES,
    FAMILY,
    SLOTS,
    Design,
    enumerate_designs,
    render,
    slots_for,
    space_size,
)
from aurelis.authoring.standin import scripted_author
from aurelis.authoring.tables import AuthoringAttempt
from aurelis.core.errors import IntegrityViolation
from aurelis.desks.costs import costs_for
from aurelis.engines.local import LocalEngine
from aurelis.org.desks import Desk
from aurelis.platform.llm.providers import MockProvider
from aurelis.research.states import HypothesisState
from aurelis.runtime import Runtime
from aurelis.strategy.markets import Assumption
from aurelis.strategy.states import Origin, Portability

_DESK = Desk.CRYPTO
_BARS = 600
"""Enough bars that the longest lookback still leaves a window to trade in,
and few enough that seventy-two of them run in a test."""


@pytest.fixture
def company(settings, clock) -> Runtime:  # type: ignore[no-untyped-def]
    """A staffed company whose provider answers authoring questions."""
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=scripted_author))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _cites(runtime: Runtime) -> Citations:
    return Citations(task_ref="TSK-0001", failure_ref=None)


# ------------------------------------------------- the space is closed and live


def test_the_space_is_enumerated_rather_than_multiplied() -> None:
    """The branches have different widths, so a product of slot sizes is wrong
    — and wrong in the direction that overstates the search."""
    designs = enumerate_designs()
    assert len(designs) == space_size() == 72
    assert len(set(designs)) == len(designs), "no design is reachable twice"

    by_family: dict[str, int] = {}
    for design in designs:
        by_family[design.family] = by_family.get(design.family, 0) + 1
    assert by_family == {"momentum": 24, "mean_reversion": 24, "rotation": 24}

    # Direction is never offered on the cross-sectional branch: the signal
    # cannot take a short, so the choice would be a knob with no hole behind it.
    assert all(not d.has("direction") for d in designs if d.family == "rotation")
    assert all(not d.has("breadth") for d in designs if d.family != "rotation")


def test_no_authorable_choice_is_inert() -> None:
    """A knob that cannot change a number is decoration, and decoration in a
    preregistration makes the search look wider than it was.

    This test is the reason ``threshold`` became a real parameter of the
    rotation signal: offered on that branch, all three values returned an
    identical Sharpe, because the signal never read it.
    """
    engine = LocalEngine()

    def measure(design: Design) -> Decimal:
        spec = render(design, desk=_DESK, bars=_BARS)
        return engine.run(spec).metrics.get("sharpe").value

    def base(family: str) -> list[tuple[str, str]]:
        return [
            (slot.name, family if slot.name == FAMILY else slot.keys[0])
            for slot in slots_for(family)
        ]

    for slot in SLOTS:
        family = "rotation" if slot.name == "breadth" else "momentum"
        picks = base(family)
        results = set()
        for key in slot.keys:
            if slot.name == FAMILY:
                results.add(measure(Design(tuple(base(key)))))
                continue
            varied = [(name, key if name == slot.name else chosen) for name, chosen in picks]
            results.add(measure(Design(tuple(varied))))
        assert len(results) > 1, f"{slot.name} changes nothing and is decoration"


def test_every_reachable_design_runs() -> None:
    """A design an agent can pick but the company cannot measure would be a
    trap in the option set."""
    engine = LocalEngine()
    for design in enumerate_designs():
        artifact = engine.run(render(design, desk=_DESK, bars=_BARS))
        assert artifact.metrics.get("sharpe") is not None


# --------------------------------------------- the agent cannot author a defect


def test_the_agent_cannot_author_its_own_costs_universe_or_warmup() -> None:
    """The three knobs the defect taxonomy plants are not on the menu.

    ``COST_UNDERSTATED``, ``SURVIVORSHIP`` and ``LOOKAHEAD`` are what M10 scores
    the company's own critic on catching. An authoring surface that offered them
    would let an agent manufacture exactly the result that critic exists to
    refuse.
    """
    forbidden = {"costs", "cost", "fee", "spread", "slippage", "universe", "warmup"}
    assert not forbidden & {slot.name for slot in SLOTS}

    desk_costs = costs_for(_DESK).engine_costs()
    for design in enumerate_designs():
        spec = render(design, desk=_DESK, bars=_BARS)
        assert spec.universe.point_in_time is True
        assert spec.backtest.costs == desk_costs
        assert spec.backtest.warmup_bars == spec.signal.lookback
        assert spec.data.bars == _BARS


def test_the_author_is_shown_no_result_from_the_data_it_will_be_measured_on() -> None:
    """Choosing after seeing the answers is selection, not authoring.

    ``material_for`` takes no session, no engine and no artifact, and the
    signature is the guarantee. This checks the stronger claim it implies: not
    one figure the author was shown is a measurement of any design in the space.
    """
    material = material_for(_DESK, bars=_BARS, citations=Citations(task_ref="TSK-0001"))
    assert tuple(material) == MATERIAL_SECTIONS

    shown = {str(value) for section in material.values() for value in section.values()}
    engine = LocalEngine()
    for design in enumerate_designs():
        metrics = engine.run(render(design, desk=_DESK, bars=_BARS)).metrics
        for name in ("sharpe", "total_return", "max_drawdown"):
            assert str(metrics.get(name).value) not in shown


# ------------------------------------------------------ the agent does the work


def test_an_agent_authors_a_whole_strategy_from_a_closed_set(
    company: Runtime,
) -> None:
    """Every field the synthesis surface requires, answered by the agent."""
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(company.provider, company.synthesis, clock=company.clock)
        authored = author.author(
            session,
            desk=_DESK,
            agent_ref=agent,
            bars=_BARS,
            citations=_cites(company),
        )
        components = company.synthesis.components_of(session, authored.version_ref)

    assert authored.design.family in {"momentum", "mean_reversion", "rotation"}
    assert {slot for slot, _ in authored.design.picks} == {
        s.name for s in slots_for(authored.design.family)
    }
    assert len(components) == len(authored.design.picks)
    assert authored.novelty is not None
    assert authored.novelty.total == len(components)
    assert authored.spec.signal.kind == authored.design.family


def test_the_rationale_on_every_component_is_the_agents_own_words(
    company: Runtime,
) -> None:
    """A component is a claim about why something should work. One with no
    stated reasoning is a parameter somebody tried."""
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(company.provider, company.synthesis, clock=company.clock)
        authored = author.author(
            session, desk=_DESK, agent_ref=agent, bars=_BARS, citations=_cites(company)
        )
        components = company.synthesis.components_of(session, authored.version_ref)

    reasons = {turn.slot: turn.reasoning for turn in authored.turns}
    for component in components:
        slot = component.spec["slot"]
        assert reasons[slot], f"{slot} was answered with no reasoning"
        assert reasons[slot] in component.rationale
        assert component.author == authored.agent_ref
        assert component.origin_ref == authored.origin_ref


def test_choosing_to_take_the_other_side_is_recorded_as_an_assumption(
    company: Runtime,
) -> None:
    """An assumption is a fact about what a rule needs, not an opinion — so it
    is implied by the choice rather than asserted by the agent, and it moves the
    portability matrix without anyone deciding that it should."""
    long_short = Design(
        (
            (FAMILY, "momentum"),
            ("lookback", "one_day"),
            ("threshold", "any_move"),
            ("direction", "long_short"),
        )
    )
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(company.provider, company.synthesis, clock=company.clock)
        authored = author._write(  # noqa: SLF001 - the design is fixed on purpose
            session,
            agent_ref=agent,
            desk=_DESK,
            design=long_short,
            spec=render(long_short, desk=_DESK, bars=_BARS),
            reasons={
                name: "a stated reason, long enough to be a claim"
                for name, _ in long_short.picks
            },
            origin=Origin.INVENTED,
            origin_ref="TSK-0001",
            weaknesses=("regime_break: it may simply stop holding",),
            at=company.clock.now(),
        )
        components = company.synthesis.components_of(session, authored.version_ref)
        portability = company.synthesis.check_portability(session, authored.version_ref)

    assert any(
        Assumption.SHORT_SELLING.value in component.assumes for component in components
    )
    blocked = [
        desk
        for desk, (status, _) in portability.items()
        if status == Portability.INAPPLICABLE.value
    ]
    assert blocked, "a rule that needs to short is not portable to a market that cannot"


# ------------------------------------------------------------- the refusals


def test_an_answer_outside_the_design_space_authors_nothing(
    company: Runtime,
) -> None:
    """A half-authored strategy would be finished by the software and recorded
    as the agent's design."""
    broken = MockProvider(responder=lambda _r: "ANSWER: whatever_i_like\nBECAUSE: taste.")
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(_Wrapped(broken), company.synthesis, clock=company.clock)
        with pytest.raises(AuthoringRefused) as caught:
            author.author(
                session,
                desk=_DESK,
                agent_ref=agent,
                bars=_BARS,
                citations=_cites(company),
            )
        assert caught.value.slot == FAMILY
        assert author.turns[-1].refused
        assert company.synthesis  # nothing was written:
        assert not _versions(company, session)


def test_a_justification_citing_an_unshown_figure_authors_nothing(
    company: Runtime,
) -> None:
    """An agent that reasoned to a design using a number nobody gave it has not
    reasoned, and the design is not recorded as reasoned."""
    liar = MockProvider(
        responder=lambda _r: "ANSWER: momentum\nBECAUSE: it returned 0.9312 last year."
    )
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(_Wrapped(liar), company.synthesis, clock=company.clock)
        with pytest.raises(AuthoringRefused) as caught:
            author.author(
                session,
                desk=_DESK,
                agent_ref=agent,
                bars=_BARS,
                citations=_cites(company),
            )
        assert isinstance(caught.value.cause, UnsourcedFigures)
        assert not _versions(company, session)


def test_a_design_with_no_origin_is_not_authored(company: Runtime) -> None:
    """``NOTHING`` is offered on every question, and refused on this one.

    Abstention exists because a surface without it produces an agent that finds
    something every time. Provenance is the exception: it is the field the
    company's claim to have created anything rests on, and an uncited creation
    is unfalsifiable.
    """
    assert NOTHING in origin_question(Citations(task_ref="TSK-0001")).keys

    abstaining = MockProvider(
        responder=lambda r: (
            f"ANSWER: {NOTHING}\nBECAUSE: no idea."
            if "come from" in r.messages[-1].content
            else scripted_author(r)
        )
    )
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(_Wrapped(abstaining), company.synthesis, clock=company.clock)
        with pytest.raises(AuthoringRefused) as caught:
            author.author(
                session,
                desk=_DESK,
                agent_ref=agent,
                bars=_BARS,
                citations=_cites(company),
            )
    assert caught.value.slot == "origin"


def test_a_design_whose_author_names_no_weakness_is_not_composed(
    company: Runtime,
) -> None:
    """M8's rule, now answered by the agent: every composition has a regime it
    does not survive, and an author who cannot name one has not looked."""
    silent = MockProvider(
        responder=lambda r: (
            f"ANSWER: {NOTHING}\nBECAUSE: it survives everything."
            if "not survive" in r.messages[-1].content
            else scripted_author(r)
        )
    )
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(_Wrapped(silent), company.synthesis, clock=company.clock)
        with pytest.raises(AuthoringRefused) as caught:
            author.author(
                session,
                desk=_DESK,
                agent_ref=agent,
                bars=_BARS,
                citations=_cites(company),
            )
    assert caught.value.slot == "weakness"
    assert {choice.key for choice in WEAKNESSES}, "the weakness set is closed"


def test_an_agent_without_the_write_scope_cannot_author(company: Runtime) -> None:
    """The separation of duty is enforced by the database, not by this module.

    The Critic is deliberately a different agent from the Architect, and it
    cannot quietly become the author by being handed the seat.
    """
    with company.database.session() as session:
        critic = company.roster.by_handle(session, "CRITIC").ref

    with company.database.session() as session:
        author = StrategyAuthor(company.provider, company.synthesis, clock=company.clock)
        try:
            author.author(
                session,
                desk=_DESK,
                agent_ref=critic,
                bars=_BARS,
                citations=_cites(company),
            )
        except Exception as error:  # noqa: BLE001 - the database raises, not us
            # Rolled back here rather than by the context manager, because the
            # refusal arrives as an aborted transaction: the guard is a trigger,
            # so the write never reached a state anything could commit.
            session.rollback()
            message = str(error)
        else:  # pragma: no cover - reaching this is the failure
            message = ""

    assert "may not write strategy_version" in message


# ------------------------------------------------- the search is on the record


def test_the_search_is_declared_not_the_pick(company: Runtime) -> None:
    """The company charges itself for the space, not for the one design it ran.

    An agent shown seventy-two alternatives has searched seventy-two; nothing in
    the record can establish which it implicitly weighed, and understating a
    false-discovery denominator manufactures confidence out of arithmetic.
    """
    outcome = run_authoring(company, span=Decimal("0.1"))
    assert outcome.declared_cells == space_size() == 72
    assert outcome.trials_in_family == 72

    with company.database.session() as session:
        registration = company.research.registration(session, outcome.registration_ref)
    assert registration.declared_cells == 72
    assert registration.locked_at is not None


def test_a_second_attempt_costs_more_in_the_denominator(company: Runtime) -> None:
    """Authoring is cheap, so a company that let an agent author until
    something passed would have built a parameter miner with a rationale
    field. The second attempt pays for the second search."""
    first = run_authoring(company, span=Decimal("0.1"))
    second = run_authoring(company, span=Decimal("0.1"))
    assert second.trials_in_family == first.trials_in_family + space_size()
    assert second.declared_cells == space_size()

    # And the second attempt has something the first did not: the company's own
    # recorded failure. A graveyard exists to be cited, and by the second pass
    # there is one -- so the origin is no longer "reasoned out under the task".
    assert first.authored.origin is Origin.INVENTED
    assert second.authored.origin is Origin.DERIVED_FROM_FAILURE
    assert second.authored.origin_ref == first.hypothesis_ref


def test_the_authored_version_is_what_ran(company: Runtime) -> None:
    """The preregistration locks the spec the agent's components render to, and
    the experiment is rebuilt from the lock rather than from a variable."""
    outcome = run_authoring(company, span=Decimal("0.1"))
    with company.database.session() as session:
        registration = company.research.registration(session, outcome.registration_ref)
        attempt = session.query(AuthoringAttempt).one()

    assert registration.spec_digest == outcome.authored.spec.digest()
    assert attempt.spec_digest == registration.spec_digest
    assert attempt.version_ref == outcome.authored.version_ref
    assert attempt.space == 72
    assert attempt.declared_cells >= attempt.space


# ------------------------------------------------------------- the honest result


def test_the_company_reports_that_it_did_not_beat_the_baselines(
    company: Runtime,
) -> None:
    """The acceptance, and it is a negative one.

    A rule that cannot beat holding the asset has not found anything. The
    stand-in's cost-aware design returns less than ``always_long`` over the same
    window at the same costs, the company says so in the report, and no part of
    the pipeline is arranged to avoid saying it.
    """
    outcome = run_authoring(company, span=Decimal("0.25"))

    assert {base.kind for base in outcome.baselines} == set(BASELINES)
    hold = next(b for b in outcome.baselines if b.kind == "always_long")
    assert outcome.total_return < hold.total_return
    assert outcome.beat_baselines is False
    assert "did NOT beat" in outcome.describe()

    with company.database.session() as session:
        attempt = session.query(AuthoringAttempt).one()
        hypothesis = company.research.hypothesis(session, outcome.hypothesis_ref)
    assert attempt.beat_baselines is False
    assert hypothesis.state is not HypothesisState.CONFIRMED, (
        "a design that lost to buying and holding was not confirmed"
    )


def test_the_verdict_says_how_much_data_would_have_settled_it(
    company: Runtime,
) -> None:
    """UNDERPOWERED without the shortfall reads as a defect in the design
    rather than a statement about how much data the claim needs — and invites
    somebody to go and tune the strategy, which is the wrong response."""
    outcome = run_authoring(company, span=Decimal("0.25"))
    assert outcome.bars == 2190
    assert outcome.bars_required > 0
    if outcome.shortfall:
        assert outcome.years_required > Decimal("0.25")


def test_the_workshop_shows_the_attempt_that_went_nowhere(company: Runtime) -> None:
    """Mission Control gets the failed attempt too.

    A workshop page that listed only successful attempts would answer "does
    this company invent anything?" with the one number that cannot answer it,
    and the charter is explicit that the station must never be arranged to look
    successful.
    """
    from aurelis.station.pages import workshop_page

    outcome = run_authoring(company, span=Decimal("0.1"))
    with company.database.session() as session:
        html = workshop_page(session)

    assert "The Workshop" in html
    assert outcome.attempt_ref in html
    assert outcome.authored.agent_ref in html
    assert f"{outcome.declared_cells} of {space_size()}" in html
    assert "<b>no</b>" in html, "it did not beat the baselines, and the page says so"


def test_the_report_says_what_is_sitting_in_the_seat(company: Runtime) -> None:
    """The designer is a deterministic stand-in and the data is a fixture.
    Every report of an attempt says both, rather than implying a model
    designed a strategy on a market."""
    outcome = run_authoring(company, span=Decimal("0.1"))
    payload = outcome.as_payload()
    assert payload["caveat"] == CAVEAT
    assert "stand-in, not a model" in payload["caveat"]
    assert "fixture" in payload["caveat"]


# ------------------------------------------------------------------- helpers


class _Wrapped:
    """The provider signature the runtime uses: ``complete(session, request)``."""

    def __init__(self, inner: MockProvider) -> None:
        self._inner = inner
        self.name = inner.name

    def complete(self, _session: object, request: object) -> object:
        return self._inner.complete(request)  # type: ignore[arg-type]


def _versions(runtime: Runtime, session: object) -> list[str]:
    from aurelis.strategy.tables import StrategyVersion

    return [row.ref for row in session.query(StrategyVersion).all()]  # type: ignore[attr-defined]


def test_an_unknown_baseline_is_refused() -> None:
    """The references are closed too. A baseline nobody agreed on is a number
    that can be chosen after the fact."""
    from aurelis.authoring.design import baseline_spec

    like = render(enumerate_designs()[0], desk=_DESK, bars=_BARS)
    with pytest.raises(ValueError, match="not a baseline"):
        baseline_spec("momentum", desk=_DESK, bars=_BARS, like=like)


def test_a_component_still_cannot_claim_an_origin_it_cannot_cite(
    company: Runtime,
) -> None:
    """M8's citation shape check, exercised from the authoring path: an agent
    cannot pick ``derived_from_failure`` when no failure exists to cite."""
    with pytest.raises(ValueError, match="no citation is available"):
        origin_question(Citations())

    with (
        company.database.session() as session,
        pytest.raises(IntegrityViolation, match="must cite"),
    ):
        company.synthesis.author_component(
            session,
            kind=SLOTS[0].kind,
            name="crypto.family.momentum",
            spec={"slot": FAMILY, "choice": "momentum"},
            rationale="a stated reason, long enough to count as a claim",
            origin=Origin.DERIVED_FROM_FAILURE,
            origin_ref="TSK-0001",
            author=company.roster.by_handle(session, "STRAT").ref,
            desk=_DESK,
        )
