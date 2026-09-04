"""Subscription access, through the Claude Agent SDK.

The default once real model calls are wanted, because it runs on the existing
Claude subscription rather than a metered key. That is the whole reason this
provider exists: the company should be buildable and runnable before anyone has
decided on a budget.

**Cost is reported as zero, and that is a true statement rather than a missing
value.** A subscription call has no marginal dollar cost. The scarce resource is
tokens and usage allowance, so token counts are still recorded and token
budgets still bind — see :mod:`aurelis.platform.budget.ledger`, which budgets
the two currencies separately for exactly this reason.

Token counts here are **estimates**, since the SDK does not always report
usage. They are labelled as such wherever they surface. A budget enforced
against an estimate is a real limitation and is stated rather than hidden.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

from aurelis.core.errors import ProviderUnavailable
from aurelis.platform.llm.providers import Availability
from aurelis.platform.llm.types import LlmRequest, LlmResponse, Usage

__all__ = ["AgentSdkProvider"]


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class AgentSdkProvider:
    """Claude Agent SDK against the local subscription."""

    name = "agent_sdk"

    def __init__(self) -> None:
        self._checked: Availability | None = None

    def availability(self) -> Availability:
        if self._checked is not None:
            return self._checked
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            self._checked = Availability(
                self.name,
                False,
                "claude-agent-sdk is not installed (pip install 'aurelis[subscription]')",
            )
        else:
            self._checked = Availability(
                self.name,
                True,
                "subscription access; no marginal dollar cost, token usage still metered",
            )
        return self._checked

    def complete(self, request: LlmRequest) -> LlmResponse:
        state = self.availability()
        if not state.available:
            raise ProviderUnavailable(state.detail)

        started = time.perf_counter()
        text = asyncio.run(self._query(request))
        latency = int((time.perf_counter() - started) * 1000)

        usage = Usage(
            tokens_in=_estimate_tokens(request.system)
            + sum(_estimate_tokens(m.content) for m in request.messages),
            tokens_out=_estimate_tokens(text),
        )
        return LlmResponse(
            text=text,
            usage=usage,
            model=request.model,
            usd=Decimal("0"),  # subscription: no marginal cost
            latency_ms=latency,
        )

    async def _query(self, request: LlmRequest) -> str:
        from claude_agent_sdk import ClaudeAgentOptions, query

        prompt = "\n\n".join(m.content for m in request.messages)
        options = ClaudeAgentOptions(
            system_prompt=request.system,
            model=request.model.model,
            max_turns=1,
            allowed_tools=[],
        )
        chunks: list[str] = []
        async for message in query(prompt=prompt, options=options):
            for block in getattr(message, "content", []) or []:
                piece = getattr(block, "text", None)
                if isinstance(piece, str):
                    chunks.append(piece)
        return "".join(chunks)
