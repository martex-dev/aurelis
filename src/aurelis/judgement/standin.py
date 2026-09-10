"""A scripted judge, so the seat can be exercised without a model.

The same arrangement as every other stand-in here, and the same caveat: **this
is not an agent.** It is a deterministic function of the prompt, so the
machinery around the seat — the closed market choice, the fixed reply form,
the figure check, the forward rule, the seal, the resolver, the calibration
report — can be run offline, in CI, at no cost.

It has one policy, stated rather than tuned: **continue the most recent
24-bar move, with a confidence that grows with the size of the move.** That is
a thing a naive trend-follower believes, and it is not known to be right. On a
fixture it is a view about a random walk and the calibration report will say
so. On a market it is whatever the market says it is.

A stand-in written to be right would teach nothing.
"""

from __future__ import annotations

import re
from decimal import Decimal

from aurelis.platform.llm.types import LlmRequest

__all__ = ["scripted_judge"]

_MARKET = re.compile(r"^\s{2}([a-z0-9/.\-]+): close ", re.MULTILINE)
_CHANGE_IN_OPTION = re.compile(
    r"^\s{2}([a-z0-9/.\-]+): .*?change over 24 bars (-?\d+\.\d+)%", re.MULTILINE
)
_CHANGE_24 = re.compile(r"over 24 bars: (-?\d+\.\d+)%")
_REFERENCE = re.compile(r"reference close: (\S+)")
_SYMBOL = re.compile(r"symbol: (\S+)")
_CONFIDENCE = re.compile(r"^\s*confidence: (\d+\.\d+)$", re.MULTILINE)


def scripted_judge(request: LlmRequest) -> str:
    prompt = request.messages[-1].content

    if "Which market do you want" in prompt:
        moves = {key: Decimal(value) for key, value in _CHANGE_IN_OPTION.findall(prompt)}
        if not moves:
            offered = _MARKET.findall(prompt)
            if not offered:
                return "ANSWER: nothing\nBECAUSE: nothing was offered."
            return (
                f"ANSWER: {offered[0]}\n"
                "BECAUSE: it is the first market with a recording, and none shows "
                "a 24 bar move to weigh."
            )
        key = max(sorted(moves), key=lambda k: abs(moves[k]))
        return (
            f"ANSWER: {key}\n"
            f"BECAUSE: it has the largest move over 24 bars, {moves[key]}%, and a "
            "stand-in continues the largest recent move."
        )

    if "State your view on" in prompt:
        symbol_match = _SYMBOL.search(prompt)
        change_match = _CHANGE_24.search(prompt)
        reference = _REFERENCE.search(prompt)
        if symbol_match is None or change_match is None or reference is None:
            return "DIRECTION: nothing\n"
        change = Decimal(change_match.group(1))
        if change == 0:
            return "DIRECTION: nothing\n"
        direction = "up" if change > 0 else "down"
        confidence = min(Decimal("0.85"), Decimal("0.55") + abs(change) / Decimal(20))
        return (
            "HORIZON: 24h\n"
            f"DIRECTION: {direction}\n"
            f"CONFIDENCE: {confidence.quantize(Decimal('0.01'))}\n"
            f"THESIS: {symbol_match.group(1)} moved {change}% over the last 24 bars "
            f"from a reference close of {reference.group(1)}. A stand-in continues "
            "the most recent move and expects the close at the horizon to be on "
            "the same side.\n"
            "WRONG_IF: the move over the last 24 bars reverses before the horizon.\n"
        )

    if "Attack this view" in prompt:
        stated = _CONFIDENCE.search(prompt)
        confidence = Decimal(stated.group(1)) if stated else Decimal("0.5")
        if confidence > Decimal("0.6"):
            return (
                "VERDICT: broken\n"
                f"ATTACK: a confidence of {confidence} on a move over 24 bars is more "
                "than the tape supports; a move that size reverses as often as it "
                "continues before the horizon."
            )
        return (
            "VERDICT: stands\n"
            "ATTACK: the view is modest and the tape offers nothing that argues "
            "the other way over the horizon."
        )

    if "Respond to the attack" in prompt:
        if "verdict: broken" in prompt:
            return (
                "RESPONSE: revise\n"
                "CONFIDENCE: 0.55\n"
                "BECAUSE: the attack is fair and the view is kept at a lower confidence."
            )
        return (
            "RESPONSE: hold\n"
            "BECAUSE: the attack does not change the reading of the tape."
        )

    return f"[stand-in] {prompt[:120]}"
