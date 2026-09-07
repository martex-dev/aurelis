"""Revising a design the company already measured.

M15 stopped after one attempt, on purpose, and said why: a revision loop is
exactly where authoring turns into mining, and it should not be added without
deciding first what stops it. This is that loop, and the thing that stops it is
:mod:`aurelis.authoring.campaign` — a budget declared before the first attempt
and a correction applied to the last.

Two rules shape a revision, and both are about keeping the record true.

**Exactly one slot changes.** A revision that rewrote every choice would be a
new design wearing a lineage, and the ancestry chain would say something false
about how the company got there. So the agent is asked two closed questions —
*which one thing do you change*, then *what do you change it to* — and
:meth:`~aurelis.strategy.synthesis.Synthesis.mutate` records the swap as a new
version superseding the old one.

**The family is not revisable.** Changing the kind of edge being claimed is not
a revision of this idea, it is a different idea; the components would share no
thesis and the lineage would connect two things that have nothing to do with
each other. It also keeps the revision space the same width on every branch,
which is what makes the campaign's declared cells countable in advance rather
than dependent on the path taken.

This is also where the agent is allowed, for the first time, to **see its own
result**. That is not a relaxation of the preregistration rule; it is what a
preregistered budget buys. Outside a campaign the material is structural only,
because a design chosen after seeing the answers is a selection. Inside one,
the width of the whole search was declared before the first attempt and the
final number is corrected for it, so the agent may learn from what it measured.
"""

from __future__ import annotations

from typing import Any

from aurelis.agents.decide import Choice, Question
from aurelis.authoring.design import FAMILY, Design, Slot, slots_for

__all__ = [
    "REVISABLE",
    "revised",
    "revision_material",
    "revision_space",
    "what_to_change_question",
    "which_slot_question",
]


def revisable_slots(family: str) -> tuple[Slot, ...]:
    """The slots a revision may touch on this branch. Never the family."""
    return tuple(slot for slot in slots_for(family) if slot.name != FAMILY)


REVISABLE = 6
"""How many one-slot revisions any design has.

The same on every branch, and checked by a test rather than trusted: the two
single-name families offer three other lookbacks, two other thresholds and one
other direction; the cross-sectional one offers three, two and one other
breadth. Equal widths are what let a campaign declare its cells before it knows
which branch the agent will pick.
"""


def revision_space(design: Design) -> int:
    """How many designs are one change away from this one."""
    return sum(
        len(slot.choices) - 1
        for slot in revisable_slots(design.family)
        if design.has(slot.name)
    )


def which_slot_question(design: Design) -> Question:
    """Which one thing changes.

    Every option names the choice currently in place, because an agent asked to
    change something it cannot see is guessing.
    """
    options = tuple(
        Choice(
            slot.name,
            f"currently {design.get(slot.name)} — {slot.prompt.rstrip('?').lower()}",
        )
        for slot in revisable_slots(design.family)
        if design.has(slot.name)
    )
    return Question(
        prompt="Your design was measured. Change exactly one thing. Which?",
        options=options,
        multiple=False,
    )


def what_to_change_question(design: Design, slot: Slot) -> Question:
    """What that one thing becomes. The current value is not on the menu.

    Offering it would let a revision be a no-op that still costs a cell and
    still produces a paragraph of reasoning about why nothing changed.
    """
    current = design.get(slot.name)
    options = tuple(
        choice for choice in slot.choices if choice.key != current
    )
    return Question(
        prompt=f"{slot.prompt} It is currently {current}.",
        options=options,
        multiple=False,
    )


def revised(design: Design, slot_name: str, key: str) -> Design:
    """The design with one slot changed, in the same order as the original."""
    if not design.has(slot_name):
        raise KeyError(f"{slot_name} is not part of this design")
    if slot_name == FAMILY:
        raise ValueError(
            "the family is not revisable: a different kind of edge is a "
            "different idea, and a lineage joining the two would say something "
            "false about how the company got here"
        )
    if design.get(slot_name) == key:
        raise ValueError(
            f"{slot_name} is already {key}; a revision that changes nothing "
            "still costs a cell and still produces a justification"
        )
    return Design(
        tuple(
            (name, key if name == slot_name else chosen)
            for name, chosen in design.picks
        )
    )


def revision_material(
    base: dict[str, Any],
    *,
    design: Design,
    metrics: dict[str, str],
    baselines: dict[str, str],
    attempt: int,
    budget: int,
    already_tried: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The structural material, plus what the previous attempt measured.

    The result is shown, and the budget with it. An agent revising without
    knowing how many attempts remain would be optimising a sequence it cannot
    see the end of, which is a different task from the one the campaign
    declared.

    ``already_tried`` is the campaign's whole history, not just the last step,
    and it was added because a real model needed it. Shown only the previous
    attempt and told it had done worse, the model reverted -- correctly, and
    straight onto a design the campaign had already measured, spending a
    declared cell to re-learn a number it had been told. An agent cannot avoid
    repeating itself if it is not shown what it has done.
    """
    added = {
        "your_previous_design": design.as_payload(),
        "what_it_measured": dict(metrics),
        "what_doing_nothing_measured": dict(baselines),
        "designs_already_measured": dict(already_tried or {}),
        # Not "budget". The structural material already has a section by that
        # name -- the research budget, in bars -- and this one silently
        # replaced it, so a revising agent could not see how much data it had.
        # A merge that can overwrite is a merge that will.
        "campaign": {
            "this attempt": attempt,
            "attempts in the campaign": budget,
            "declared before the first": "yes",
        },
    }
    clash = set(base) & set(added)
    if clash:
        raise ValueError(
            f"revision material would overwrite {sorted(clash)} in the "
            "structural material. What a revision adds is the result, and "
            "nothing else."
        )
    return {**base, **added}
