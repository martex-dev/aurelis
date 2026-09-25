"""A scripted method writer, so evolution runs offline. Not an agent."""

from __future__ import annotations

from aurelis.platform.llm.types import LlmRequest

__all__ = ["scripted_method"]


def scripted_method(request: LlmRequest) -> str:  # noqa: ARG001 - one answer for all
    return (
        "METHOD: Look first at whether the last day's move came with volume; a move on "
        "thin volume is noise, so say nothing. State a view only when the move and the "
        "flow agree, keep confidence near 0.55 unless the evidence is unusual, and "
        "prefer the longer horizons, which one bar cannot decide.\n"
        "BECAUSE: the record shows confident calls on thin moves, and a coin toss beats "
        "confidence that the evidence does not support.\n"
    )
