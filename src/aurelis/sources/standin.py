"""A scripted source chooser, so the seat runs offline. Not an agent."""

from __future__ import annotations

from aurelis.platform.llm.types import LlmRequest

__all__ = ["scripted_sources"]


def scripted_sources(request: LlmRequest) -> str:
    prompt = request.messages[-1].content
    if "Which of these sources" not in prompt:
        return f"[stand-in] {prompt[:120]}"
    return (
        "SOURCES: coindesk, theblock\n"
        "BECAUSE: both carry exchange listings, halts and flow stories about the "
        "instruments the company follows, which are the events its mechanisms fire on.\n"
    )
