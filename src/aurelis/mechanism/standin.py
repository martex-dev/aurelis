"""A scripted mechanism author, so the discovery seat runs offline.

The same caveat as every other stand-in: **this is not an agent.** It reads
the pattern out of the material and states a mechanism with a fixed causal
story, so the whole loop — state, seal, generate predictions, score, decide
scheme-or-graveyard — can run in CI at no cost. It always states *up*, which
means on a fixture (a random walk) its out-of-sample predictions will not beat
the base rate, and the sweep will retire it. That is the machinery working: a
mechanism with no real edge is killed by its own record.
"""

from __future__ import annotations

import re

from aurelis.platform.llm.types import LlmRequest

__all__ = ["scripted_discovery"]

_TRIGGER = re.compile(r"^\s+trigger: (\S+)", re.MULTILINE)


def scripted_discovery(request: LlmRequest) -> str:
    prompt = request.messages[-1].content
    if "State a mechanism for this pattern" not in prompt:
        return f"[stand-in] {prompt[:120]}"
    match = _TRIGGER.search(prompt)
    trigger = match.group(1) if match else "the trigger"
    return (
        "MECHANISM: forced-flow continuation\n"
        "DIRECTION: up\n"
        "HORIZON: 24\n"
        "CONFIDENCE: 0.55\n"
        f"WHY: a {trigger} marks a burst of forced buying by participants who "
        "must fill within a window, and price continues in that direction until "
        "the flow is exhausted.\n"
        "OTHER_SIDE: passive liquidity providers who lean against the move and "
        "are run over while the forced flow lasts.\n"
        "DECAY: it dies as market makers widen quotes around the trigger once "
        "the pattern is known, and it cannot absorb size beyond the daily volume "
        "of the smallest name it fires on.\n"
    )
