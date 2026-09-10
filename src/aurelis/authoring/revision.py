"""Revising a rule the company already measured.

M15 stopped after one attempt, on purpose, and said why: a revision loop is
exactly where authoring turns into mining, and it should not be added without
deciding first what stops it. :mod:`aurelis.authoring.campaign` is the loop
with the rule attached — a budget declared before the first attempt and a
correction applied to the last.

A revision is the same seat writing a different rule. It is shown the rule it
wrote, what that rule measured, what doing nothing measured, every rule the
campaign has already tried and how each scored, and how many attempts remain.
That is the one place in the system an agent may see a result before choosing
a rule, and it is permitted here for exactly one reason: the whole width was
declared before the first attempt and the final number is corrected for it.
"""

from __future__ import annotations

from typing import Any

from aurelis.agents.interpret import FIGURE_RULE
from aurelis.rules.language import Program

__all__ = ["REVISION_FORM", "revision_material"]

REVISION_FORM = (
    "Your rule was measured. Write a revised rule in the same language, or "
    "keep the idea and change what it trades on -- but do not resubmit a rule "
    "the campaign has already measured. Reply in exactly this form and nothing "
    "else:\n"
    "RULE:\n"
    "<one clause per line>\n"
    "RATIONALE: <what you changed and why, one to three sentences>\n\n"
    "Or, if nothing is worth revising toward: RULE: nothing\n\n"
    "The numbers inside RULE are yours to choose. RATIONALE may cite them and "
    f"the figures above, and nothing else. {FIGURE_RULE}"
)


def revision_material(
    base: dict[str, Any],
    *,
    program: Program,
    metrics: dict[str, str],
    baselines: dict[str, str],
    attempt: int,
    budget: int,
    already_tried: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The structural material, plus what the previous attempt measured.

    ``already_tried`` is the campaign's whole history, not just the last step,
    and it was added because a real model needed it: shown only the previous
    attempt and told it had done worse, the model reverted -- correctly, and
    straight onto a rule the campaign had already measured. An agent cannot
    avoid repeating itself if it is not shown what it has done.
    """
    added = {
        "your_previous_rule": program.text,
        "what_it_measured": dict(metrics),
        "what_doing_nothing_measured": dict(baselines),
        "rules_already_measured": dict(already_tried or {}),
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
