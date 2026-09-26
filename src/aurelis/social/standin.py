"""A scripted curator, so the curation seat runs offline. Not an agent."""

from __future__ import annotations

from aurelis.platform.llm.types import LlmRequest

__all__ = ["scripted_curation"]


def scripted_curation(request: LlmRequest) -> str:
    prompt = request.messages[-1].content
    if "Which voices should the company follow" not in prompt:
        return f"[stand-in] {prompt[:120]}"
    return (
        "FOLLOW: none\n"
        "DROP: none\n"
        "BECAUSE: no record offered clears the bar for its family, so the company keeps "
        "reading what it reads and lets the records since each follow grow.\n"
    )
