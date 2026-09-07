"""M18 — the seats meet a real model.

Every seat in this company was designed against a deterministic stand-in that
always answered in form, because it was written to. The first time a real model
sat in the authoring seat it produced **zero usable answers in five**: three
abstentions and two justifications citing figures it had derived rather than
been shown.

Neither was the model behaving badly, and that is the point of this file. It
declined because the material honestly said the data was a fixture too short to
support a claim. It derived because the instruction said "cite only figures
shown above", which a careful reader takes as *reason only from these*. Both
were fixed by saying what was meant, and the rate went to five in five without
a single guard being weakened.

These tests hold the fix in place and keep the measurement honest.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aurelis.agents.decide import NOTHING, Choice, Question
from aurelis.agents.interpret import FIGURE_RULE
from aurelis.authoring.attempt import CAVEAT, caveat_for, run_authoring
from aurelis.authoring.revision import revision_material
from aurelis.authoring.standin import scripted_author
from aurelis.core.enums import ModelTier
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.rehearsal import Conformance, Sample, rehearse
from aurelis.platform.llm.seating import seat_provider, stands_in
from aurelis.runtime import Runtime

_QUESTION = Question(
    prompt="Which applies?",
    options=(Choice("alpha", "the first"), Choice("beta", "the second")),
    multiple=False,
)
_MATERIAL = {"evidence": {"drawdown": "0.42", "trades": "17"}}


class _Provider:
    """A provider that replies from a script, one answer per call."""

    name = "mock"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, request):  # type: ignore[no-untyped-def]
        self.prompts.append(request.messages[-1].content)
        from aurelis.platform.llm.types import LlmResponse, Usage

        return LlmResponse(
            text=self._replies.pop(0), usage=Usage(1, 1), model=request.model
        )


# ------------------------------------------------------- the figure rule


def test_the_figure_rule_says_what_the_guard_actually_enforces() -> None:
    """"Cite only figures shown above" invited exactly the derivation the
    guard refuses. A rule the instructions did not state is a rule the model
    was never given a chance to follow."""
    assert "EXACTLY as written" in FIGURE_RULE
    assert "convert" in FIGURE_RULE
    assert FIGURE_RULE in _QUESTION.render()


def test_the_figure_rule_carries_no_figures_of_its_own() -> None:
    """It is appended to the prompt, and the prompt is scanned for permitted
    figures. A digit here would quietly widen what an answer may cite."""
    assert not any(character.isdigit() for character in FIGURE_RULE)


def test_abstention_is_still_offered_after_the_rewrite() -> None:
    """The fix was to the instructions, not to the guards. A seat that stopped
    offering `nothing` would be a seat that finds something every time."""
    assert NOTHING in _QUESTION.keys
    assert f"{NOTHING}: none of the above applies" in _QUESTION.render()


# ------------------------------------------------------ the measurement


def test_a_rehearsal_classifies_an_answer_the_way_a_turn_would() -> None:
    """Exactly the path a real turn takes, in the same order.

    A rehearsal that accepted answers the seat would reject would be measuring
    something the company never uses.
    """
    provider = _Provider(
        [
            "ANSWER: alpha\nBECAUSE: the drawdown was 0.42.",
            f"ANSWER: {NOTHING}\nBECAUSE: none of these fit.",
            "ANSWER: beta\nBECAUSE: it lost 0.91 of its value.",
            "I would rather not answer in that form.",
            "ANSWER: alpha\nBECAUSE: it made 17 trades.",
        ]
    )
    result = rehearse(
        provider,
        question=_QUESTION,
        material=_MATERIAL,
        system="be a critic",
        tier=ModelTier.MID,
        samples=5,
    )

    assert [sample.outcome for sample in result.samples] == [
        "usable",
        "abstained",
        "unsourced",
        "unparseable",
        "usable",
    ]
    assert result.usable == 2
    assert result.total == 5
    assert result.choices == {"alpha": 2, "beta": 1}
    assert "2/5 usable" in result.describe()


def test_a_rehearsal_does_not_measure_the_cache() -> None:
    """Rehearsing against a cache would report one answer's conformance
    ``samples`` times, which is the one number this cannot afford to get
    wrong."""
    provider = _Provider(["ANSWER: alpha\nBECAUSE: it held."] * 3)
    rehearse(
        provider,
        question=_QUESTION,
        material=_MATERIAL,
        system="be a critic",
        samples=3,
    )
    assert len(provider.prompts) == 3
    assert len(set(provider.prompts)) == 3, "each sample carries its own nonce"


def test_a_rehearsal_needs_a_sample() -> None:
    with pytest.raises(ValueError, match="at least one sample"):
        rehearse(
            _Provider([]),
            question=_QUESTION,
            material=_MATERIAL,
            system="x",
            samples=0,
        )


def test_conformance_notices_a_model_that_always_says_the_same_thing() -> None:
    """Five identical answers conform perfectly and decide nothing. Both real
    seats did exactly this on their first rehearsal."""
    result = Conformance(
        model="m",
        tier=ModelTier.MID,
        samples=tuple(Sample("usable", ("alpha",), "because") for _ in range(5)),
    )
    assert result.usable == 5
    assert result.choices == {"alpha": 5}
    assert len(result.choices) == 1
    assert "not" in result.as_payload()["note"]


# --------------------------------------------------- who is in the seat


def test_the_stand_in_answers_only_for_the_offline_provider(settings) -> None:  # type: ignore[no-untyped-def]
    """Leaving the seats wired to a script would have made the stand-in
    permanent: three commands that say they seat an agent and always seat a
    script, whatever the workspace is configured to use."""
    assert stands_in("mock")
    assert not stands_in("agent_sdk")

    offline = seat_provider(settings, scripted_author)
    assert isinstance(offline, MockProvider)

    settings.provider = "agent_sdk"
    assert seat_provider(settings, scripted_author) is None, (
        "None means the runtime builds whatever the workspace configured"
    )


def test_the_report_says_which_of_the_two_actually_answered() -> None:
    """A caveat that keeps being printed after it stops being true is worse
    than none: it is the sentence a reader trusts to tell them what they are
    looking at.

    A real model authored a strategy through this exact path and the report
    still said a deterministic stand-in had done it.
    """
    assert caveat_for("mock") == CAVEAT
    assert "stand-in, not a model" in caveat_for("mock")

    real = caveat_for("agent_sdk")
    assert "stand-in" not in real
    assert "agent_sdk" in real
    assert "model's own" in real
    # The data caveat survives either way: a real model on a fixture is still
    # a fixture.
    for text in (caveat_for("mock"), real):
        assert "fixture rather than a market" in text


def test_an_attempt_records_the_caveat_that_was_true_when_it_ran(
    settings, clock  # type: ignore[no-untyped-def]
) -> None:
    built = Runtime.build(
        settings, clock=clock, provider=MockProvider(responder=scripted_author)
    )
    built.initialise()
    built.staff()
    try:
        outcome = run_authoring(built, span=Decimal("0.1"))
    finally:
        built.close()
    assert outcome.caveat == CAVEAT
    assert outcome.as_payload()["caveat"] == CAVEAT


# ------------------------------------------- what the campaign learned


def test_a_revision_is_shown_everything_the_campaign_has_measured() -> None:
    """An agent cannot avoid repeating itself if it is not shown what it has
    done.

    Shown only the previous attempt and told it had done worse, a real model
    reverted -- correctly, and straight onto a design the campaign had already
    measured, spending a declared cell to re-learn a number it had been told.
    """
    from aurelis.authoring.design import enumerate_designs

    material = revision_material(
        {"desk": {"market": "Crypto"}},
        design=enumerate_designs()[0],
        metrics={"sharpe": "0.01"},
        baselines={"always_long": "0.24"},
        attempt=3,
        budget=5,
        already_tried={"family=momentum, lookback=one_week": "sharpe 0.005"},
    )
    assert material["designs_already_measured"] == {
        "family=momentum, lookback=one_week": "sharpe 0.005"
    }


def test_a_quota_failure_reads_as_a_state_rather_than_a_crash() -> None:
    """The scarce resource on a subscription is allowance, and running out of
    it is an ordinary operating state the company will meet far more often
    than it meets a bug."""
    pytest.importorskip("claude_agent_sdk")
    from claude_agent_sdk import ResultError

    from aurelis.core.errors import ProviderUnavailable
    from aurelis.platform.llm.agent_sdk import _translate

    translated = _translate(
        ResultError(
            "Claude Code returned an error result: You've hit your session "
            "limit · resets 7:40pm (Europe/Sofia)"
        )
    )
    assert isinstance(translated, ProviderUnavailable)
    assert "allowance is exhausted" in str(translated)
    assert "resets 7:40pm" in str(translated), "it says when, because 'later' is not advice"
    assert "unaffected" in str(translated)


def test_a_campaign_refuses_to_re_measure_a_design_it_has_already_tried(
    settings, clock  # type: ignore[no-untyped-def]
) -> None:
    """Re-testing a known number costs a declared cell and returns nothing.

    Driven here by a responder that reverts on purpose. A real model did the
    same thing for a good reason -- it was told its revision had done worse and
    went back -- which is why the history is now shown to it as well as guarded
    against.
    """
    import re

    from aurelis.authoring.campaign import run_campaign

    def reverting(request):  # type: ignore[no-untyped-def]
        prompt = request.messages[-1].content
        if "Change exactly one thing" in prompt:
            return "ANSWER: lookback\nBECAUSE: it is the slowest knob to move."
        if "It is currently" in prompt:
            if re.search(r"^\s+one_week:", prompt, re.MULTILINE):
                return "ANSWER: one_week\nBECAUSE: back to the slowest setting."
            return "ANSWER: six_hours\nBECAUSE: the fastest setting available."
        return scripted_author(request)

    built = Runtime.build(
        settings, clock=clock, provider=MockProvider(responder=reverting)
    )
    built.initialise()
    built.staff()
    try:
        outcome = run_campaign(built, span=Decimal("0.1"), budget=4)
    finally:
        built.close()

    assert len(outcome.attempts) == 2, "it stopped when the third would repeat"
    assert outcome.refusals
    assert "already measured" in outcome.refusals[-1]
    digests = [item.authored.design.digest() for item in outcome.attempts]
    assert len(set(digests)) == len(digests), "nothing was measured twice"
