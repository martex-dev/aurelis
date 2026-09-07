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
                "claude-agent-sdk installed; no marginal dollar cost, token "
                "usage still metered. Login is NOT verified here -- the SDK "
                "spawns Claude Code, and whether that process is authenticated "
                "is only knowable by making a call (aurelis model check)",
            )
        return self._checked

    def complete(self, request: LlmRequest) -> LlmResponse:
        state = self.availability()
        if not state.available:
            raise ProviderUnavailable(state.detail)

        started = time.perf_counter()
        try:
            text = asyncio.run(self._query(request))
        except Exception as error:  # noqa: BLE001 - narrowed immediately below
            raise _translate(error) from error
        latency = int((time.perf_counter() - started) * 1000)

        usage = Usage(
            tokens_in=_estimate_tokens(request.system)
            + sum(_estimate_tokens(m.content) for m in request.messages),
            tokens_out=_estimate_tokens(text),
            # Said out loud on every call, because token budgets bind against
            # this and a budget enforced on an approximation should not look
            # like one enforced on a measurement.
            estimated=True,
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


def _translate(error: Exception) -> Exception:
    """Turn an SDK failure into something the company can act on.

    The first real call this provider ever made came back as a raw traceback
    forty frames deep ending in ``Not logged in -- Please run /login``. That is
    a configuration state, not a crash: the wiring worked, the process started,
    and it declined. Reporting it as an unhandled exception would put an
    operator through a stack trace to learn something a sentence covers.

    Anything that is not a recognised SDK error is passed through unchanged.
    Swallowing an unknown failure into "provider unavailable" would hide a real
    bug behind a reassuring message.
    """
    try:
        from claude_agent_sdk import ClaudeSDKError
    except ImportError:  # pragma: no cover - unreachable once a call has run
        return error
    if not isinstance(error, ClaudeSDKError):
        return error

    detail = str(error)
    if "Not logged in" in detail or "/login" in detail:
        return ProviderUnavailable(
            "the Claude Code process this SDK spawns is not logged in. Run "
            "`claude` and sign in, then try again. Nothing was spent."
        )
    return ProviderUnavailable(f"the Claude Agent SDK could not complete the call: {detail}")
