"""A scripted designer, so the author's seat can be exercised without a model.

The same arrangement as :mod:`aurelis.training.standin`, and the same caveat:
**this is not an agent.** Every model call in this repository runs against the
mock provider — no credentials, no network, no cost — and a mock that echoes
its input cannot answer a multiple-choice question. This is a deterministic
function of the prompt, so the machinery around the seat can be run and scored:
the closed slots, the parse, the figure check, the refusal path, the citation
shape check, and the preregistration that follows.

It has **one policy, stated here rather than tuned**: *trade less when trading
costs more.* It reads the desk's round-trip charge out of the material it was
shown and, above a threshold, picks the slowest option in every slot — the
longest lookback, the largest required move, no shorting, the most
concentrated holding. Below it, the opposite.

That policy is a reasonable thing for a cost-aware designer to believe and it
is **not known to be right**. The point of running it is to find out what the
company's own measurement says about it, and the answer this repository gets is
in :mod:`aurelis.authoring.attempt`: it does not beat holding the asset. A
stand-in written to produce a winner would have taught nothing, and would have
been the fake functionality the charter forbids.

Point the runtime at a real provider and the same code path asks a real model.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from aurelis.platform.llm.types import LlmRequest

__all__ = ["EXPENSIVE", "scripted_author"]

EXPENSIVE = Decimal("30")
"""The round-trip charge, in basis points, above which the stand-in slows down.

Every desk the company has opened charges more than this, so on the desks that
exist the stand-in always takes the patient branch. The threshold is kept
rather than hard-coded away because it is the whole content of the policy:
remove it and the stand-in has no reason for anything it picks.
"""

_ROUND_TRIP = re.compile(r"round trip:\s*(-?\d+(?:\.\d+)?)\s*bps", re.IGNORECASE)

_SLOW: dict[str, str] = {
    "family": "momentum",
    "lookback": "one_week",
    "threshold": "two_percent",
    "direction": "long_only",
    "breadth": "concentrated",
}
_FAST: dict[str, str] = {
    "family": "rotation",
    "lookback": "six_hours",
    "threshold": "any_move",
    "direction": "long_short",
    "breadth": "paired",
}

_SLOTS: dict[str, tuple[str, ...]] = {
    "family": ("momentum", "mean_reversion", "rotation"),
    "lookback": ("six_hours", "one_day", "three_days", "one_week"),
    "threshold": ("any_move", "half_percent", "two_percent"),
    "direction": ("long_only", "long_short"),
    "breadth": ("concentrated", "paired"),
}

_ORIGIN_ORDER = ("derived_from_failure", "adapted", "invented")
_ORIGIN_BECAUSE: dict[str, str] = {
    "derived_from_failure": (
        "the company already paid to learn this once, and answering a recorded "
        "failure is cheaper than claiming the idea was new."
    ),
    "adapted": (
        "the shape of this rule came from work the company inherited rather "
        "than from reasoning done here, and saying so is what keeps the "
        "novelty count honest."
    ),
    "invented": (
        "no recorded failure and no inherited trial was offered, so this was "
        "reasoned out under the task and is cited as such."
    ),
}
"""One justification per origin, because a stand-in whose reasoning did not
match its answer would pass the figure check while reading as confabulation --
and it did, until a demonstration printed the two side by side."""

_WEAKNESSES = ("choppy", "cost_shock")


def _offered(prompt: str, keys: tuple[str, ...]) -> bool:
    """Whether every key in a slot appears as an option in this prompt."""
    return all(re.search(rf"^\s+{re.escape(key)}:", prompt, re.MULTILINE) for key in keys)


def _round_trip(prompt: str) -> Decimal | None:
    match = _ROUND_TRIP.search(prompt)
    if match is None:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:  # pragma: no cover - the regex guarantees digits
        return None


def scripted_author(request: LlmRequest) -> str:
    """Answer one authoring question from the figures in the prompt.

    Every justification cites the round-trip charge and nothing else, because
    that is the only figure the policy actually uses — and citing a number it
    did not use would be the confabulation the figure check exists to catch,
    passing the check by luck.
    """
    prompt = request.messages[-1].content
    charge = _round_trip(prompt)
    patient = charge is None or charge > EXPENSIVE
    because = (
        f"At {charge} bps a round trip the design should trade as little as it can."
        if charge is not None
        else "No charge was shown, so the design assumes trading is expensive."
    )

    for origin in _ORIGIN_ORDER:
        if _offered(prompt, (origin,)):
            return f"ANSWER: {origin}\nBECAUSE: {_ORIGIN_BECAUSE[origin]}"

    if _offered(prompt, _WEAKNESSES):
        return (
            f"ANSWER: {', '.join(_WEAKNESSES)}\n"
            f"BECAUSE: {because} A market with no direction pays the charge "
            "and earns nothing, and a wider one erases what is left."
        )

    for slot, keys in _SLOTS.items():
        if _offered(prompt, keys):
            table = _SLOW if patient else _FAST
            return f"ANSWER: {table[slot]}\nBECAUSE: {because}"

    return "ANSWER: nothing\nBECAUSE: none of these options were recognised."
