"""Asking an agent to *decide*, and refusing anything that is not a decision.

:mod:`aurelis.agents.interpret` asks a model to interpret material and checks
that it only stated figures it was shown. That is the right guard for prose,
and prose is not enough for the thing this company most needs an agent to do:
**pick from a closed set, and be scored on the pick.**

A critique is the case that matters. M10 built a suite that plants known
defects in twelve worlds and counts what a critic catches — but the critic was
a `Playbook`, a set of numeric thresholds. Its own docstring said what was
missing:

    What the harness proves today is that the company can measure a procedure
    and refuse to ship a worse one; what it will measure when agents reason for
    themselves is the same thing, through the same harness, with the agent in
    place of the thresholds.

This module is the seat that agent sits in. Four rules hold it shut.

**The answer space is closed.** A question carries its options, the options are
rendered into the prompt, and an answer naming anything else is a
:class:`UndecidableAnswer` — not a warning, not a best-effort match. A critic
that could invent a defect type could not be scored against a planted one,
which is the same reason the objection taxonomy is closed.

**The reasoning is figure-checked.** Every numeral in the justification must
appear in the material the agent was shown, by exactly the rule
:mod:`aurelis.agents.interpret` already enforces. An agent that reasons its way
to a conclusion using a number nobody gave it has not reasoned, it has
confabulated.

**Abstention is an answer.** ``NOTHING`` is always available and always
legitimate. A decision surface with no way to say "none of these" produces a
critic that alleges something every time, which is precisely the failure mode
the null scenarios exist to catch.

**The decision is recorded with its reasoning.** Not the prose instead of the
pick, and not the pick instead of the prose: a choice nobody can audit is
indistinguishable from a coin toss that got lucky.

What runs in CI behind this is the mock provider, exactly as every other model
call in this repository. The *mechanism* is real — closed options, figure
checks, refusals, scoring on the same worlds — and the reasoner behind it in a
test is scripted. Point it at a real provider and the same code path asks a
real model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from aurelis.agents.interpret import (
    FIGURE_RULE,
    allowed_figures,
    render_material,
    unsourced_numerals,
)
from aurelis.core.enums import ModelTier
from aurelis.platform.budget.ledger import Spend
from aurelis.platform.llm.routing import model_for
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

__all__ = [
    "NOTHING",
    "Choice",
    "Decision",
    "Question",
    "UndecidableAnswer",
    "decide_as",
]

NOTHING = "nothing"
"""The abstention. Always offered, always legitimate.

A decision surface with no way to say "none of these" produces an agent that
finds something every time — and a critic that always finds something scores
badly on the null scenarios, which is the whole reason they are in the
catalogue.
"""

_ANSWER = re.compile(r"^\s*answer\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_BECAUSE = re.compile(r"^\s*because\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE | re.DOTALL)


class UndecidableAnswer(ValueError):
    """The model answered with something that is not one of the options."""

    def __init__(self, offered: tuple[str, ...], got: str) -> None:
        super().__init__(
            f"answer {got!r} is not one of {list(offered)}. The option set is "
            "closed: an agent that could name something outside it could not "
            "be scored against a planted defect, and a near-miss matched "
            "loosely would be the system deciding rather than the agent."
        )
        self.offered = offered
        self.got = got


@dataclass(frozen=True, slots=True)
class Choice:
    """One thing an agent may pick, and what picking it means."""

    key: str
    describes: str

    def render(self) -> str:
        return f"  {self.key}: {self.describes}"


@dataclass(frozen=True, slots=True)
class Question:
    """What the agent is asked, and the complete set of permitted answers."""

    prompt: str
    options: tuple[Choice, ...]
    multiple: bool = False
    """Whether more than one option may be named. A critique is multiple: a
    specification can have two defects, and a surface that forced one would
    make the second a guaranteed miss."""

    @property
    def keys(self) -> tuple[str, ...]:
        return (*(c.key for c in self.options), NOTHING)

    def render(self) -> str:
        joined = "\n".join(c.render() for c in self.options)
        how = (
            "Name every option that applies, comma-separated"
            if self.multiple
            else "Name exactly one option"
        )
        return (
            f"{self.prompt}\n\n"
            f"Options:\n{joined}\n"
            f"  {NOTHING}: none of the above applies\n\n"
            f"{how}, or `{NOTHING}`. Reply in exactly this form and nothing "
            "else:\n"
            "ANSWER: <option keys>\n"
            "BECAUSE: <one or two sentences>\n\n"
            f"{FIGURE_RULE}"
        )


@dataclass(frozen=True, slots=True)
class Decision:
    """What the agent chose, why, and what it cost."""

    chosen: frozenset[str]
    reasoning: str
    spend: Spend
    raw: str

    @property
    def abstained(self) -> bool:
        return not self.chosen

    def describe(self) -> str:
        picked = ", ".join(sorted(self.chosen)) if self.chosen else NOTHING
        return f"{picked} — {self.reasoning[:120]}"

    def as_payload(self) -> dict[str, Any]:
        return {
            "chosen": sorted(self.chosen),
            "reasoning": self.reasoning,
            "abstained": self.abstained,
        }


def parse(answer: str, question: Question) -> tuple[frozenset[str], str]:
    """Pull the pick and the reasoning out of a reply, or refuse.

    Deliberately strict. A model that did not answer in the required form has
    not answered the question, and salvaging the intent from prose would put
    the parser's judgement into the agent's record.
    """
    match = _ANSWER.search(answer)
    if match is None:
        raise UndecidableAnswer(question.keys, answer.strip()[:80] or "<empty>")

    named = [
        token.strip().lower()
        for token in match.group(1).replace(";", ",").split(",")
        if token.strip()
    ]
    if not named:
        raise UndecidableAnswer(question.keys, "<empty>")

    permitted = set(question.keys)
    for token in named:
        if token not in permitted:
            raise UndecidableAnswer(question.keys, token)
    if not question.multiple and len(named) > 1:
        raise UndecidableAnswer(question.keys, ", ".join(named))

    chosen = frozenset(t for t in named if t != NOTHING)
    if NOTHING in named and chosen:
        raise UndecidableAnswer(
            question.keys, f"{NOTHING} together with {sorted(chosen)}"
        )

    because = _BECAUSE.search(answer)
    reasoning = because.group(1).strip() if because else ""
    return chosen, reasoning


def decide_as(
    provider: Any,
    session: Any,
    *,
    agent_ref: str,
    question: Question,
    material: dict[str, Any],
    system: str,
    tier: ModelTier = ModelTier.MID,
    max_tokens: int = 300,
    task_ref: str | None = None,
    model: str | None = None,
) -> Decision:
    """Ask an agent to choose from a closed set, and refuse anything else.

    Raises :class:`UndecidableAnswer` if the reply names something outside the
    options, and
    :class:`~aurelis.agents.interpret.UnsourcedFigures` if the reasoning cites
    a number the agent was not shown. Both are recorded against the agent by
    the caller, which is what an Agent Behavior Auditor samples for.
    """
    rendered = f"{render_material(material)}\n\n{question.render()}"
    # The tier decides the model, and the charter decides the tier. Callers
    # that pass an explicit id are pinning one deliberately; everything else
    # goes through the router, which is what stopped every call site in the
    # company from asking a real provider for a model called "mock-1".
    model_id = model or model_for(provider.name, tier)
    response = provider.complete(
        session,
        LlmRequest(
            model=ModelRef(
                provider=provider.name, model=model_id, tier=tier, max_tokens=max_tokens
            ),
            system=system,
            messages=(Message("user", rendered),),
            actor=agent_ref,
            task_ref=task_ref,
        ),
    )

    chosen, reasoning = parse(response.text, question)

    # The same figure rule prose is held to. An agent that reasoned its way to
    # a conclusion using a number nobody gave it has not reasoned.
    #
    # The rendered question counts as material, because it *is* material the
    # agent was shown. M14's options were prose and this made no difference;
    # M15's carry numbers -- a lookback of 168 bars, a threshold of 0.02 -- and
    # without this an agent could not justify its pick by referring to the pick.
    # A guard that refuses an answer for citing the question is not checking
    # sourcing, it is punishing specificity.
    permitted = allowed_figures(material, {"options": question.render()})
    invented = unsourced_numerals(reasoning, permitted)
    if invented:
        from aurelis.agents.interpret import UnsourcedFigures

        raise UnsourcedFigures(invented, len(permitted))

    return Decision(
        chosen=chosen,
        reasoning=reasoning,
        spend=Spend(response.usd, response.usage.total),
        raw=response.text,
    )
