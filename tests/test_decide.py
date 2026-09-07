"""M14 — an agent in the seat the playbook occupied.

M10 said, in as many words, that the harness would not change when agents
reasoned for themselves: the playbook would be replaced by the agent and the
same twelve worlds would mark the same twelve answers. These tests are that
claim, plus the guards that make the seat safe to sit in.

**What runs behind the seat here is not a model.** Every model call in this
repository is against the mock provider, so a deterministic stand-in supplies
the answers. What is tested is the machinery: a closed answer set, a
figure-checked justification, a refusal path, and scoring against measured
truth.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aurelis.agents.decide import (
    NOTHING,
    Choice,
    Question,
    UndecidableAnswer,
    decide_as,
    parse,
)
from aurelis.agents.interpret import UnsourcedFigures
from aurelis.engines.synthetic import shared_bench
from aurelis.engines.synthetic.scenarios import CATALOGUE, scenario
from aurelis.meetings.taxonomy import MARKET_DEFECTS
from aurelis.meetings.types import ObjectionType
from aurelis.platform.llm.providers import MockProvider
from aurelis.runtime import Runtime
from aurelis.training.critic import AgentCritic, critique_question
from aurelis.training.playbook import INCUMBENT
from aurelis.training.seating import run_seating
from aurelis.training.standin import scripted_critic
from aurelis.training.suite import TrainingSuite

_QUESTION = Question(
    prompt="Which apply?",
    options=(
        Choice("survivorship", "was the universe chosen with hindsight?"),
        Choice("lookahead", "is it earning from its priming window?"),
    ),
    multiple=True,
)


# ------------------------------------------------------- the answer is closed


def test_an_answer_outside_the_option_set_is_refused() -> None:
    """A critic that could invent a defect could not be scored against a
    planted one — the same reason the objection taxonomy is closed."""
    chosen, why = parse("ANSWER: survivorship\nBECAUSE: the universe.", _QUESTION)
    assert chosen == {"survivorship"}
    assert why == "the universe."

    with pytest.raises(UndecidableAnswer, match="not one of"):
        parse("ANSWER: vibes\nBECAUSE: a feeling.", _QUESTION)


def test_a_reply_that_is_not_an_answer_is_refused() -> None:
    """Salvaging intent from prose would put the parser's judgement into the
    agent's record."""
    with pytest.raises(UndecidableAnswer):
        parse("I think there may be some survivorship here.", _QUESTION)
    with pytest.raises(UndecidableAnswer):
        parse("ANSWER:\nBECAUSE: nothing", _QUESTION)


def test_abstention_is_always_available_and_never_mixed() -> None:
    """A surface with no way to say 'none of these' produces a critic that
    finds something every time."""
    assert NOTHING in _QUESTION.keys
    chosen, _ = parse(f"ANSWER: {NOTHING}\nBECAUSE: nothing moved.", _QUESTION)
    assert chosen == frozenset()

    with pytest.raises(UndecidableAnswer, match="together with"):
        parse(f"ANSWER: {NOTHING}, survivorship\nBECAUSE: both.", _QUESTION)


def test_a_single_choice_question_refuses_two_answers() -> None:
    single = Question("Pick one", _QUESTION.options, multiple=False)
    with pytest.raises(UndecidableAnswer):
        parse("ANSWER: survivorship, lookahead\nBECAUSE: both.", single)


def test_the_question_only_offers_defects_that_apply() -> None:
    """An objection that cannot apply is noise, and noise is what stops real
    objections being read."""
    question = critique_question((ObjectionType.SURVIVORSHIP,))
    assert [c.key for c in question.options] == ["survivorship"]
    assert question.multiple, "a specification can have two defects"
    assert NOTHING in question.keys


# ---------------------------------------------------- the reasoning is checked


def test_a_justification_citing_an_unshown_figure_is_refused(
    runtime: Runtime,
) -> None:
    """An agent that reasons to a conclusion using a number nobody gave it has
    not reasoned, it has confabulated."""
    provider = MockProvider(
        responder=lambda _r: "ANSWER: survivorship\nBECAUSE: drawdown hit 0.9312."
    )
    runtime_provider = _Wrapped(provider)
    with (
        runtime.database.session() as session,
        pytest.raises(UnsourcedFigures, match="not present in"),
    ):
        decide_as(
            runtime_provider,
            session,
            agent_ref="AG-0001",
            question=_QUESTION,
            material={"evidence": {"max_drawdown": "0.1234"}},
            system="be a critic",
        )


def test_a_justification_citing_a_shown_figure_is_accepted(
    runtime: Runtime,
) -> None:
    provider = _Wrapped(
        MockProvider(responder=lambda _r: "ANSWER: survivorship\nBECAUSE: it moved 0.1234.")
    )
    with runtime.database.session() as session:
        decision = decide_as(
            provider,
            session,
            agent_ref="AG-0001",
            question=_QUESTION,
            material={"evidence": {"max_drawdown": "0.1234"}},
            system="be a critic",
        )
    assert decision.chosen == {"survivorship"}
    assert "0.1234" in decision.reasoning
    assert not decision.abstained


class _Wrapped:
    """The provider signature the runtime uses: ``complete(session, request)``."""

    def __init__(self, inner: MockProvider) -> None:
        self._inner = inner
        self.name = inner.name

    def complete(self, _session: object, request: object) -> object:
        return self._inner.complete(request)  # type: ignore[arg-type]


# ------------------------------------------- the agent is scored, not believed


@pytest.fixture
def seated(settings, clock) -> Runtime:  # type: ignore[no-untyped-def]
    """A company whose provider answers critique questions deterministically."""
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=scripted_critic))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def test_an_agent_takes_the_seat_a_playbook_occupied(seated: Runtime) -> None:
    """Same evidence, same bench, same marking. Only the decider changes."""
    suite = TrainingSuite(bench=shared_bench())
    with seated.database.session() as session:
        critic = AgentCritic(
            seated.provider,
            session,
            agent_ref="AG-0009",
            specialty=frozenset(MARKET_DEFECTS),
        )
        result = suite.run_agent(critic)

    assert len(result.marks) == len(CATALOGUE)
    assert result.playbook.startswith("agent:")
    assert result.score.planted == suite.run(INCUMBENT).score.planted, (
        "the agent is marked against the same planted defects as the procedure"
    )
    assert any(critique.detail.get("reasoning") for critique in result.critiques)


def test_a_turn_that_cannot_be_read_alleges_nothing(seated: Runtime) -> None:
    """A critique nobody could act on is not a critique, and the marking
    counts every real defect on that scenario as missed."""
    broken = _Wrapped(MockProvider(responder=lambda _r: "I decline to answer."))
    with seated.database.session() as session:
        critic = AgentCritic(
            broken, session, agent_ref="AG-0009", specialty=frozenset(MARKET_DEFECTS)
        )
        critique = critic.critique(scenario("SC-05"), shared_bench())

    assert critique.alleged == frozenset()
    assert critique.considered, "it was asked, and could not answer"
    assert critic.errors and "UndecidableAnswer" in critic.errors[0]
    assert critic.turns[0].refused


def test_an_agent_with_no_applicable_defect_is_asked_nothing(
    seated: Runtime,
) -> None:
    """A specialty that does not apply to a specification is not a silence to
    the agent's credit, and not a question either."""
    with seated.database.session() as session:
        critic = AgentCritic(
            seated.provider,
            session,
            agent_ref="AG-0009",
            specialty=frozenset({ObjectionType.SURVIVORSHIP}),
        )
        # SC-01 presents a point-in-time universe, so survivorship cannot apply.
        critique = critic.critique(scenario("SC-01"), shared_bench())
    assert critique.considered == frozenset()
    assert critique.alleged == frozenset()


# -------------------------------------------- the company weighs the agent


def test_the_company_weighs_the_agent_against_the_procedure(
    seated: Runtime,
) -> None:
    """The acceptance: an agent is judged by the same instrument as the
    procedure it would replace, and the gate decides.

    The stand-in catches everything the suite plants — including the defect the
    procedure misses — and raises objections on specifications that do not have
    one. Finding more is not the same as being better, and the gate refuses on
    counts rather than on taste.
    """
    outcome = run_seating(seated, agent_handle="CRITIC")

    assert outcome.agent.score.caught == 8
    assert outcome.procedure.score.caught == 7
    assert outcome.caught_more and outcome.alarmed_more
    assert not outcome.ships
    assert outcome.verdict == "mixed"
    assert "cries wolf" in outcome.detail
    assert outcome.refusals == 0, outcome.errors


def test_a_strictly_better_agent_would_ship(seated: Runtime) -> None:
    """The gate is not a rejection stamp: it refuses a trade-off, not an agent.

    On survivorship alone the stand-in catches all three planted cases and
    raises nothing spurious, so against a procedure blunted on that one check
    it finds strictly more at no cost — and ships. Both sides are restricted to
    the same specialty, because a comparison where one faced more questions
    than the other would report arithmetic rather than evidence.
    """
    only = frozenset({ObjectionType.SURVIVORSHIP})
    blunted = INCUMBENT.revised(ObjectionType.SURVIVORSHIP, degradation=Decimal("50"))

    outcome = run_seating(seated, agent_handle="CRITIC", base=blunted, specialty=only)
    assert outcome.procedure.score.caught == 0
    assert outcome.agent.score.caught == 3
    assert outcome.agent.score.false_alarms <= outcome.procedure.score.false_alarms
    assert outcome.ships
    assert outcome.verdict == "agent_better"


def test_the_seat_says_what_is_sitting_in_it(seated: Runtime) -> None:
    """The reasoner in this repository is a deterministic stand-in, and every
    report of a seating says so rather than implying a model answered."""
    outcome = run_seating(seated, agent_handle="CRITIC")
    payload = outcome.as_payload()
    assert "stand-in, not a model" in payload["caveat"]
