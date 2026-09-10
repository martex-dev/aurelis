"""A scripted author, so the author's seat can be exercised without a model.

The same arrangement as :mod:`aurelis.training.standin`, and the same caveat:
**this is not an agent.** Every model call in this repository runs against the
mock provider, and a mock that echoes its input cannot write a rule. This is a
deterministic function of the prompt, so the machinery around the seat can be
run and scored: the parse, the figure check, the refusal path, the
preregistration, the campaign and its correction.

It has **one policy, stated here rather than tuned**: *trade less when trading
costs more.* It reads the desk's round-trip charge out of the material and,
above a threshold, writes a slow, long-only trend rule; below it, a fast rule
that takes both sides. Revising, it walks the other way one step at a time --
a shorter window, then a lower threshold -- because the patient rule lost to
holding the asset, and stops when it has nowhere left to go.

That policy is a reasonable thing for a cost-aware author to believe and it is
**not known to be right**. A stand-in written to produce a winner would have
taught nothing.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from aurelis.platform.llm.types import LlmRequest

__all__ = ["EXPENSIVE", "scripted_author"]

EXPENSIVE = Decimal("30")
"""The round-trip charge, in basis points, above which the stand-in slows down."""

_ROUND_TRIP = re.compile(r"round trip:\s*(-?\d+(?:\.\d+)?)\s*bps", re.IGNORECASE)
_PREVIOUS = re.compile(r"^\s*your previous rule:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_RULE = re.compile(r"ret\((\d+)\) > (\d+(?:\.\d+)?) -> long")

_WINDOWS: tuple[int, ...] = (168, 72, 24, 6)
_THRESHOLDS: tuple[str, ...] = ("0.02", "0.005", "0")

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


def _offered(prompt: str, key: str) -> bool:
    return re.search(rf"^\s+{re.escape(key)}:", prompt, re.MULTILINE) is not None


def _round_trip(prompt: str) -> Decimal | None:
    match = _ROUND_TRIP.search(prompt)
    if match is None:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:  # pragma: no cover - the regex guarantees digits
        return None


def _next_step(window: int, threshold: str) -> tuple[int, str] | None:
    """One step toward trading more: shorter window first, then lower bar."""
    if window in _WINDOWS and _WINDOWS.index(window) < len(_WINDOWS) - 1:
        return _WINDOWS[_WINDOWS.index(window) + 1], threshold
    if threshold in _THRESHOLDS and _THRESHOLDS.index(threshold) < len(_THRESHOLDS) - 1:
        return window, _THRESHOLDS[_THRESHOLDS.index(threshold) + 1]
    return None


def scripted_author(request: LlmRequest) -> str:
    prompt = request.messages[-1].content
    charge = _round_trip(prompt)

    if "Your rule was measured" in prompt:
        previous = _PREVIOUS.search(prompt)
        found = _RULE.search(previous.group(1)) if previous else None
        step = _next_step(int(found.group(1)), found.group(2)) if found else None
        if step is None:
            return (
                "RULE: nothing\n"
                "RATIONALE: every step this policy walks has been taken, so there "
                "is nothing left for it to revise toward."
            )
        window, threshold = step
        return (
            "RULE:\n"
            f"ret({window}) > {threshold} -> long\n"
            f"RATIONALE: the previous rule did not earn its charge back, so this "
            f"one trades sooner, on a {window} bar window above {threshold}."
        )

    for origin in _ORIGIN_ORDER:
        if _offered(prompt, origin):
            return f"ANSWER: {origin}\nBECAUSE: {_ORIGIN_BECAUSE[origin]}"

    if "Write one rule" in prompt:
        patient = charge is None or charge > EXPENSIVE
        if patient:
            because = (
                f"At {charge} bps a round trip the rule should trade as little as it can, "
                "so it waits for a move over a long window before taking a side."
                if charge is not None
                else "No charge was shown, so the rule assumes trading is expensive "
                "and waits for a move over a long window."
            )
            return (
                "RULE:\n"
                "ret(168) > 0.02 -> long\n"
                f"RATIONALE: {because}\n"
                "WEAKNESS: a market with no direction pays the costs and earns nothing."
            )
        return (
            "RULE:\n"
            "ret(6) > 0 -> long\n"
            "ret(6) < 0 -> short\n"
            f"RATIONALE: At {charge} bps a round trip the rule can afford to trade "
            "often, so it takes both sides of the most recent move.\n"
            "WEAKNESS: a market that keeps reversing pays the costs on every bar."
        )

    return f"[stand-in] {prompt[:120]}"
