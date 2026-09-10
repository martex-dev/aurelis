"""Can the model in front of us actually answer a closed question?

Every seat in this company is shut on four sides: a closed option set, a
figure-checked justification, an abstention that is always available, and a
refusal path for anything unreadable. Those guards were designed against a
deterministic stand-in that always answered in form, because it was written to.

The first time a real model sat in the authoring seat it produced **zero usable
answers in five**: three abstentions and two justifications citing figures it
had derived rather than been shown. Neither was the model behaving badly. It
declined because the material honestly said the data was a fixture too short to
support a claim, and it derived because the instruction said "cite only figures
shown above", which a careful reader takes as *reason only from these*.

Both were fixed by saying what was meant. What this module adds is the thing
that made the fix checkable: **conformance is a number, sampled on demand, not
an impression.** A guard that silently rejects most of what a model says is
worse than no guard, because the seat looks occupied and produces nothing --
and without a measurement, the only symptom is a command that fails.

Nothing here is scored against truth. A high conformance rate says the seat is
*usable*, not that the answers are good; whether they are good is what the
M10 suite and the M16 correction are for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aurelis.agents.decide import Question, UndecidableAnswer, parse
from aurelis.agents.interpret import (
    allowed_figures,
    render_material,
    unsourced_numerals,
)
from aurelis.core.enums import ModelTier
from aurelis.platform.llm.routing import model_for
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

__all__ = ["Conformance", "Sample", "rehearse"]


@dataclass(frozen=True, slots=True)
class Sample:
    """One answer, and what became of it."""

    outcome: str
    """``usable``, ``abstained``, ``unsourced`` or ``unparseable``."""

    chosen: tuple[str, ...]
    detail: str

    def describe(self) -> str:
        picked = ", ".join(self.chosen) if self.chosen else "-"
        return f"{self.outcome:12} {picked:24} {self.detail[:90]}"


@dataclass(frozen=True, slots=True)
class Conformance:
    """How much of what the model said the company could actually use."""

    model: str
    tier: ModelTier
    samples: tuple[Sample, ...] = field(default=())

    def count(self, outcome: str) -> int:
        return sum(1 for sample in self.samples if sample.outcome == outcome)

    @property
    def usable(self) -> int:
        return self.count("usable")

    @property
    def total(self) -> int:
        return len(self.samples)

    @property
    def choices(self) -> dict[str, int]:
        """What it picked, and how often. A model that answers usably and
        always identically is conforming without deciding anything."""
        tally: dict[str, int] = {}
        for sample in self.samples:
            for key in sample.chosen:
                tally[key] = tally.get(key, 0) + 1
        return tally

    def describe(self) -> str:
        parts = ", ".join(
            f"{outcome} {self.count(outcome)}"
            for outcome in ("usable", "abstained", "unsourced", "unparseable")
            if self.count(outcome)
        )
        return f"{self.model} at {self.tier.value}: {self.usable}/{self.total} usable ({parts})"

    def as_payload(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "tier": self.tier.value,
            "samples": self.total,
            "usable": self.usable,
            "abstained": self.count("abstained"),
            "unsourced": self.count("unsourced"),
            "unparseable": self.count("unparseable"),
            "choices": self.choices,
            "note": (
                "Conformance measures whether an answer can be used, not "
                "whether it is right. Whether it is right is what the scenario "
                "suite and the selection correction are for."
            ),
        }


Reader = Callable[[str], tuple[tuple[str, ...], str, str]]
"""Parse a free-form reply into ``(chosen, reasoning, extra_material)``.

For seats that do not answer in ``ANSWER:`` form. ``extra_material`` is text
the reply itself makes citable -- a rule's own numbers -- and is added to the
permitted figures before the reasoning is checked. Raise ``ValueError`` for an
unreadable reply; return an empty ``chosen`` for an abstention.
"""


def rehearse(
    provider: Any,
    *,
    material: dict[str, Any],
    system: str,
    question: Question | None = None,
    form: str | None = None,
    reader: Reader | None = None,
    tier: ModelTier = ModelTier.MID,
    samples: int = 5,
    max_tokens: int = 300,
    actor: str = "OPERATOR",
) -> Conformance:
    """Ask the same question ``samples`` times and classify every answer.

    Each sample carries a nonce so an identical prompt is not served from the
    response cache. Rehearsing against a cache would report one answer's
    conformance ``samples`` times, which is the one number this cannot afford
    to get wrong.

    A closed seat passes ``question``; a free-form seat passes ``form`` (the
    reply form rendered after the material) and ``reader`` (how the seat
    itself parses a reply). Either way the classification is exactly the path
    a real turn takes.
    """
    if samples < 1:
        raise ValueError("a rehearsal needs at least one sample")
    if (question is None) == (form is None):
        raise ValueError("rehearse takes a closed question or a reply form, not both")
    if form is not None and reader is None:
        raise ValueError("a free-form seat needs a reader")

    tail = question.render() if question is not None else str(form)
    rendered = f"{render_material(material)}\n\n{tail}"
    permitted = allowed_figures(material, {"options": tail})
    model = model_for(provider.name, tier)
    results: list[Sample] = []

    for index in range(samples):
        response = provider.complete(
            LlmRequest(
                model=ModelRef(
                    provider=provider.name, model=model, tier=tier, max_tokens=max_tokens
                ),
                system=system,
                messages=(Message("user", f"{rendered}\n\n[sample {index}]"),),
                actor=actor,
            )
        )
        if question is not None:
            results.append(_classify(response.text, question, permitted))
        else:
            assert reader is not None
            results.append(_classify_free(response.text, reader, permitted))

    return Conformance(model=model, tier=tier, samples=tuple(results))


def _classify_free(text: str, reader: Reader, permitted: set[str]) -> Sample:
    try:
        chosen, why, extra = reader(text)
    except ValueError as error:
        return Sample("unparseable", (), str(error)[:200])
    if not chosen:
        return Sample("abstained", (), why[:200])
    invented = unsourced_numerals(why, permitted | allowed_figures({"reply": extra}))
    if invented:
        return Sample("unsourced", tuple(chosen), f"cited {sorted(invented)}")
    return Sample("usable", tuple(chosen), why[:200])


def _classify(text: str, question: Question, permitted: set[str]) -> Sample:
    """Exactly the path a real turn takes, in the same order.

    Deliberately not a looser check. A rehearsal that accepted answers the
    seat would reject would be measuring something the company never uses.
    """
    try:
        chosen, why = parse(text, question)
    except UndecidableAnswer as error:
        return Sample("unparseable", (), str(error)[:200])
    if not chosen:
        return Sample("abstained", (), why[:200])
    invented = unsourced_numerals(why, permitted)
    if invented:
        return Sample("unsourced", tuple(sorted(chosen)), f"cited {sorted(invented)}")
    return Sample("usable", tuple(sorted(chosen)), why[:200])
