"""M26 — an agent writes a rule, and the company measures it.

M15 put an agent in this seat with a menu of 72 designs. The menu is gone.
These tests are the agent writing the rule in the company's rule language,
plus the guards that stop "an agent created a strategy" from quietly becoming
untrue.

The acceptance is deliberately not "the strategy worked". It is that the
company authored a rule it did not write, declared it as one cell, measured it
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
    RULE_FORM,
    AuthoringRefused,
    Citations,
    StrategyAuthor,
    material_for,
    origin_question,
    parse_authoring,
)
from aurelis.authoring.specs import BASELINES, baseline_spec, render_spec
from aurelis.authoring.standin import scripted_author
from aurelis.authoring.tables import AuthoringAttempt
from aurelis.core.errors import IntegrityViolation
from aurelis.desks.costs import costs_for
from aurelis.org.desks import Desk
from aurelis.platform.llm.providers import MockProvider
from aurelis.research.states import HypothesisState
from aurelis.rules import parse
from aurelis.runtime import Runtime
from aurelis.strategy.markets import Assumption
from aurelis.strategy.states import ComponentKind, Origin, Portability

_DESK = Desk.CRYPTO
_BARS = 600


@pytest.fixture
def company(settings, clock) -> Runtime:  # type: ignore[no-untyped-def]
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=scripted_author))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _cites(runtime: Runtime) -> Citations:
    return Citations(task_ref="TSK-0001", failure_ref=None)


# ------------------------------------------------------------ no menu anywhere


def test_there_is_no_design_space_left_in_the_tree() -> None:
    """The brief's instruction, checked rather than remembered: no module in
    the authoring package enumerates designs, and the engine's rule signal is
    what an agent writes rather than what it picks."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("aurelis.authoring.design")
    import aurelis.authoring as authoring

    assert not hasattr(authoring, "enumerate_designs")
    assert not hasattr(authoring, "space_size")


def test_the_author_is_shown_the_language_and_no_result() -> None:
    """The material is structural only. A pure function of the desk, with no
    session, engine or artifact in its signature, so nothing in it can carry
    a measurement of the data the rule will be scored on."""
    material = material_for(_DESK, bars=_BARS, citations=Citations(task_ref="TSK-0001"))
    assert tuple(material) == MATERIAL_SECTIONS
    assert "reference" in material["the_language"]
    assert "sharpe" not in str(material).lower()
    assert material["costs"]["round trip"] == f"{costs_for(_DESK).round_trip_bps} bps"


def test_the_agent_cannot_author_its_own_costs_universe_or_warmup() -> None:
    """The three knobs the critic is scored on catching are set by the desk,
    identically for every rule."""
    slow = render_spec(parse("ret(168) > 0.02 -> long"), desk=_DESK, bars=_BARS)
    fast = render_spec(parse("ret(6) > 0 -> long\nret(6) < 0 -> short"), desk=_DESK, bars=_BARS)
    assert slow.backtest.costs == fast.backtest.costs == costs_for(_DESK).engine_costs()
    assert slow.universe.point_in_time and fast.universe.point_in_time
    assert slow.backtest.warmup_bars == 168 and fast.backtest.warmup_bars == 6
    assert not slow.backtest.allow_short and fast.backtest.allow_short


# ------------------------------------------------------------ the seat


def test_an_agent_writes_a_rule_and_the_rule_is_the_strategy(company: Runtime) -> None:
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(company.provider, company.synthesis, clock=company.clock)
        authored = author.author(
            session, desk=_DESK, agent_ref=agent, bars=_BARS, citations=_cites(company)
        )
        components = company.synthesis.components_of(session, authored.version_ref)

    assert authored.program.text == "ret(168) > 0.02 -> long"
    assert authored.spec.signal.kind == "rule"
    assert authored.spec.signal.parameters["program"] == authored.program.payload
    assert len(components) == 1 and components[0].kind == ComponentKind.SIGNAL.value
    assert components[0].spec["digest"] == authored.program.digest
    assert authored.rationale in components[0].rationale
    assert authored.novelty is not None and authored.novelty.total == 1


def test_the_rationale_and_weakness_are_the_agents_own_words(company: Runtime) -> None:
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(company.provider, company.synthesis, clock=company.clock)
        authored = author.author(
            session, desk=_DESK, agent_ref=agent, bars=_BARS, citations=_cites(company)
        )
        version = company.strategies.version(session, authored.version_ref)
    assert "bps a round trip" in authored.rationale
    assert authored.weaknesses == ("a market with no direction pays the costs and earns nothing.",)
    assert list(version.known_weaknesses) == list(authored.weaknesses)
    assert authored.turns[0].slot == "rule" and authored.turns[1].slot == "origin"


def test_a_rule_that_shorts_is_recorded_as_an_assumption(company: Runtime) -> None:
    """Implied by the rule rather than asserted by the agent, and it moves the
    portability matrix without anyone deciding that it should."""
    program = parse("ret(24) > 0 -> long\nret(24) < 0 -> short")
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = StrategyAuthor(company.provider, company.synthesis, clock=company.clock)
        authored = author._write(  # noqa: SLF001 - the rule is fixed on purpose
            session,
            agent_ref=agent,
            desk=_DESK,
            program=program,
            spec=render_spec(program, desk=_DESK, bars=_BARS),
            rationale="a stated reason, long enough to be a claim",
            origin=Origin.INVENTED,
            origin_ref="TSK-0001",
            weaknesses=("it may simply stop holding",),
            at=company.clock.now(),
        )
        components = company.synthesis.components_of(session, authored.version_ref)
        portability = company.synthesis.check_portability(session, authored.version_ref)
    assert any(Assumption.SHORT_SELLING.value in c.assumes for c in components)
    assert [d for d, (status, _) in portability.items() if status == Portability.INAPPLICABLE.value]


# ------------------------------------------------------------ the refusals


def _seat(company: Runtime, responder):  # type: ignore[no-untyped-def]
    return StrategyAuthor(
        _Wrapped(MockProvider(responder=responder)), company.synthesis, clock=company.clock
    )


def _author_with(company: Runtime, responder):  # type: ignore[no-untyped-def]
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        author = _seat(company, responder)
        with pytest.raises(AuthoringRefused) as caught:
            author.author(
                session, desk=_DESK, agent_ref=agent, bars=_BARS, citations=_cites(company)
            )
        assert not _versions(company, session), "nothing was written"
        return caught.value, author


def test_a_rule_that_does_not_parse_authors_nothing(company: Runtime) -> None:
    """The parser refuses rather than guesses. A near-miss repaired by the
    software would put the software's rule on the agent's record."""
    refused, author = _author_with(
        company,
        lambda _r: (
            "RULE:\nvolume(24) > 1 -> long\nRATIONALE: volume leads price here.\n"
            "WEAKNESS: it may not."
        ),
    )
    assert refused.slot == "rule"
    assert "not a feature" in str(refused.cause)
    assert author.turns[-1].refused


def test_a_rationale_citing_an_unshown_figure_authors_nothing(company: Runtime) -> None:
    """The numbers inside the rule are the agent's; a number in the rationale
    that is in neither the material nor the rule is invented."""
    refused, _ = _author_with(
        company,
        lambda _r: (
            "RULE:\nret(24) > 0.02 -> long\n"
            "RATIONALE: it returned 0.9312 last year on this desk.\n"
            "WEAKNESS: a reversal."
        ),
    )
    assert refused.slot == "rationale"
    assert isinstance(refused.cause, UnsourcedFigures)


def test_a_rationale_may_cite_the_rules_own_numbers(company: Runtime) -> None:
    def cites_itself(r):  # type: ignore[no-untyped-def]
        if "Write one rule" in r.messages[-1].content:
            return (
                "RULE:\nret(37) > 0.013 -> long\n"
                "RATIONALE: a 37 bar window above 0.013 is a move worth paying for.\n"
                "WEAKNESS: a market with no direction."
            )
        return scripted_author(r)

    with company.database.session() as session:
        agent = company.roster.by_handle(session, "STRAT").ref
        authored = _seat(company, cites_itself).author(
            session, desk=_DESK, agent_ref=agent, bars=_BARS, citations=_cites(company)
        )
    assert authored.program.text == "ret(37) > 0.013 -> long"


def test_a_rule_with_no_origin_is_not_authored(company: Runtime) -> None:
    assert NOTHING in origin_question(Citations(task_ref="TSK-0001")).keys
    refused, _ = _author_with(
        company,
        lambda r: (
            f"ANSWER: {NOTHING}\nBECAUSE: no idea."
            if "come from" in r.messages[-1].content
            else scripted_author(r)
        ),
    )
    assert refused.slot == "origin"


def test_a_rule_whose_author_names_no_weakness_is_not_composed(company: Runtime) -> None:
    refused, _ = _author_with(
        company,
        lambda _r: (
            "RULE:\nret(24) > 0.02 -> long\nRATIONALE: a move worth paying for on this desk.\n"
            "WEAKNESS: none"
        ),
    )
    assert refused.slot == "weakness"


def test_declining_to_write_a_rule_authors_nothing(company: Runtime) -> None:
    refused, author = _author_with(company, lambda _r: "RULE: nothing")
    assert refused.slot == "rule"
    assert "declined" in str(refused.cause)
    assert author.turns[-1].error == "declined"


def test_an_unreadable_reply_authors_nothing(company: Runtime) -> None:
    refused, _ = _author_with(company, lambda _r: "I think momentum over a day or so should work.")
    assert refused.slot == "rule"
    assert "no RULE section" in str(refused.cause)


def test_the_reply_form_is_parsed_not_interpreted() -> None:
    parsed = parse_authoring(
        "RULE:\n ret(24) > 0.02 -> long \n  ret(24) < -0.02 -> short\n"
        "RATIONALE: the move over a day is worth paying for.\nWEAKNESS: choppy markets."
    )
    assert parsed.program is not None
    assert parsed.program.text == "ret(24) > 0.02 -> long\nret(24) < -0.02 -> short"
    assert parsed.rationale.startswith("the move")
    assert parse_authoring("RULE: nothing").declined
    with pytest.raises(AuthoringRefused, match="rationale"):
        parse_authoring("RULE:\nret(24) > 0 -> long\nRATIONALE: short\nWEAKNESS: chop chop chop")
    assert "yours to choose" in RULE_FORM


def test_an_agent_without_the_write_scope_cannot_author(company: Runtime) -> None:
    """The separation of duty is enforced by the database, not by this module."""
    with company.database.session() as session:
        critic = company.roster.by_handle(session, "CRITIC").ref
    with company.database.session() as session:
        author = StrategyAuthor(company.provider, company.synthesis, clock=company.clock)
        try:
            author.author(
                session, desk=_DESK, agent_ref=critic, bars=_BARS, citations=_cites(company)
            )
        except Exception as error:  # noqa: BLE001 - the database raises, not us
            session.rollback()
            message = str(error)
        else:  # pragma: no cover - reaching this is the failure
            message = ""
    assert "may not write strategy_version" in message


# ------------------------------------------------- the search is on the record


def test_one_rule_is_one_declared_cell(company: Runtime) -> None:
    """There is no enumerable space behind a written rule to charge for. Each
    rule the company measures is one cell, and the docstrings say that this is
    a floor rather than a conservative estimate."""
    outcome = run_authoring(company, span=Decimal("0.1"))
    assert outcome.declared_cells == 1
    assert outcome.trials_in_family == 1
    with company.database.session() as session:
        registration = company.research.registration(session, outcome.registration_ref)
        attempt = session.query(AuthoringAttempt).one()
    assert registration.declared_cells == 1 and registration.locked_at is not None
    assert attempt.space == 1 and attempt.declared_cells == 1
    assert attempt.design["rule"] == outcome.authored.program.text
    assert attempt.design_digest == outcome.authored.program.digest


def test_a_second_attempt_costs_another_cell_and_cites_the_first_failure(
    company: Runtime,
) -> None:
    first = run_authoring(company, span=Decimal("0.1"))
    second = run_authoring(company, span=Decimal("0.1"))
    assert second.trials_in_family == first.trials_in_family + 1
    assert first.authored.origin is Origin.INVENTED
    assert second.authored.origin is Origin.DERIVED_FROM_FAILURE
    assert second.authored.origin_ref == first.hypothesis_ref


def test_the_authored_version_is_what_ran(company: Runtime) -> None:
    outcome = run_authoring(company, span=Decimal("0.1"))
    with company.database.session() as session:
        registration = company.research.registration(session, outcome.registration_ref)
        attempt = session.query(AuthoringAttempt).one()
    assert registration.spec_digest == outcome.authored.spec.digest()
    assert attempt.spec_digest == registration.spec_digest
    assert registration.spec["signal"]["kind"] == "rule"
    assert registration.spec["signal"]["parameters"]["program"] == outcome.authored.program.payload


# ------------------------------------------------------------- the honest result


def test_the_company_reports_that_it_did_not_beat_the_baselines(company: Runtime) -> None:
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
    assert hypothesis.state is not HypothesisState.CONFIRMED


def test_the_verdict_says_how_much_data_would_have_settled_it(company: Runtime) -> None:
    outcome = run_authoring(company, span=Decimal("0.25"))
    assert outcome.bars == 2190
    assert outcome.bars_required > 0
    if outcome.shortfall:
        assert outcome.years_required > Decimal("0.25")


def test_the_workshop_shows_the_rule_and_the_attempt_that_went_nowhere(
    company: Runtime,
) -> None:
    from aurelis.station.pages import workshop_page

    outcome = run_authoring(company, span=Decimal("0.1"))
    with company.database.session() as session:
        html = workshop_page(session)
    assert "The Workshop" in html
    assert outcome.attempt_ref in html
    assert "ret(168) &gt; 0.02 -&gt; long" in html or "ret(168) > 0.02 -> long" in html
    assert "<b>no</b>" in html


def test_the_report_says_what_is_sitting_in_the_seat(company: Runtime) -> None:
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
    like = render_spec(parse("ret(24) > 0 -> long"), desk=_DESK, bars=_BARS)
    with pytest.raises(ValueError, match="not a baseline"):
        baseline_spec("momentum", desk=_DESK, bars=_BARS, like=like)


def test_a_component_still_cannot_claim_an_origin_it_cannot_cite(company: Runtime) -> None:
    with pytest.raises(ValueError, match="no citation is available"):
        origin_question(Citations())
    with (
        company.database.session() as session,
        pytest.raises(IntegrityViolation, match="must cite"),
    ):
        company.synthesis.author_component(
            session,
            kind=ComponentKind.SIGNAL,
            name="crypto.rule.deadbeef",
            spec={"program": parse("ret(6) > 0 -> long").payload},
            rationale="a stated reason, long enough to count as a claim",
            origin=Origin.DERIVED_FROM_FAILURE,
            origin_ref="TSK-0001",
            author=company.roster.by_handle(session, "STRAT").ref,
            desk=_DESK,
        )
