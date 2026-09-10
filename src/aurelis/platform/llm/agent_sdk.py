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
import tempfile
import time
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from aurelis.core.errors import ProviderUnavailable
from aurelis.platform.llm.providers import Availability
from aurelis.platform.llm.types import LlmRequest, LlmResponse, Usage

__all__ = ["AgentSdkProvider"]


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


_NO_TOOLS: tuple[str, ...] = (
    "Bash",
    "Edit",
    "Glob",
    "Grep",
    "NotebookEdit",
    "Read",
    "Task",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Write",
)
"""Named explicitly as well as denied at the boundary.

Belt and braces on purpose. The deny callback is the guard that actually holds;
this list is what an operator reading the configuration sees, and it fails
closed if a future SDK stops calling the callback.
"""


@lru_cache(maxsize=1)
def _sandbox() -> Path:
    """An empty directory for the spawned process to sit in, and empty settings.

    Not the security boundary — the deny callback is that. This is so that a
    seat's working directory is not the repository holding the tests it is
    scored by, and so that the operator's own Claude Code configuration does
    not follow the seat in.

    That second part is not hypothetical. The first tool a seat was refused
    was not a built-in at all: it was
    ``mcp__claude_ai_Remote_Desktop_Commander__list_directory``, an MCP server
    belonging to the person running the command. The spawned process inherits
    whatever they have connected, so the reachable tool surface is not a list
    this repository can enumerate — which is exactly why the guard is a
    callback that denies everything rather than a list of names.
    """
    path = Path(tempfile.mkdtemp(prefix="aurelis-seat-"))
    (path / "settings.json").write_text("{}", encoding="utf-8")
    return path


class AgentSdkProvider:
    """Claude Agent SDK against the local subscription."""

    name = "agent_sdk"

    def __init__(self) -> None:
        self._checked: Availability | None = None
        self.refused_tools: list[str] = []
        """Tools the model reached for and was refused.

        Kept rather than discarded: an agent that keeps trying to look things
        up is telling the company its material is not enough, and that is
        worth seeing rather than silently blocking.
        """

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

    async def refuse_tool(self, tool: str, _input: Any, _context: Any) -> Any:
        """Refuse every tool, in code rather than by configuration.

        **This is the seat's most important guard.** ``allowed_tools=[]`` reads
        as *no restriction*, not as *nothing allowed*, and the first campaign
        against a real model found out how: the agent answered a design
        question by running ``Grep`` over this repository, reading
        ``authoring/standin.py`` — the file that scripts what a stand-in
        answers — and the campaign tests, and then replying. It was not
        reasoning about a market. It had found the answer key.

        A name list cannot be the guard, because the reachable surface is not
        this repository's to enumerate: the spawned process inherits the
        operator's own MCP servers, and the first tool actually refused here
        was one of those. So every tool is denied, whatever it is called.
        """
        from claude_agent_sdk import PermissionResultDeny

        self.refused_tools.append(tool)
        return PermissionResultDeny(
            message=(
                "This seat has no tools. Answer from the material in the "
                "prompt alone."
            ),
            interrupt=False,
        )

    def options(self, request: LlmRequest) -> Any:
        """The options one seat runs under. Separate so a test can read them."""
        from claude_agent_sdk import ClaudeAgentOptions

        return ClaudeAgentOptions(
            system_prompt=request.system,
            model=request.model.model,
            # Bounded, but not one. The SDK spawns Claude Code, which may
            # spend a turn thinking before it answers, and at max_turns=1 that
            # comes back as "Reached maximum number of turns (1)" with no
            # text -- intermittently, on exactly the longer prompts the
            # authoring seat sends. Four is headroom for a model that takes a
            # moment.
            max_turns=4,
            allowed_tools=[],
            disallowed_tools=list(_NO_TOOLS),
            can_use_tool=self.refuse_tool,
            # No MCP servers, and none of the operator's settings. A seat is
            # a model answering from its material, not a session inheriting
            # whatever the person running it happens to have connected.
            mcp_servers={},
            strict_mcp_config=True,
            settings=str(_sandbox() / "settings.json"),
            # Nothing of the company's to read even if a tool got through.
            cwd=str(_sandbox()),
        )

    async def _query(self, request: LlmRequest) -> str:
        from claude_agent_sdk import query

        prompt = "\n\n".join(m.content for m in request.messages)
        options = self.options(request)
        chunks: list[str] = []
        async for message in query(prompt=prompt, options=options):
            for block in getattr(message, "content", []) or []:
                piece = getattr(block, "text", None)
                if isinstance(piece, str):
                    chunks.append(piece)
        text = "".join(chunks)
        if not text.strip():
            raise ProviderUnavailable(
                "the Claude Agent SDK returned no text. The call reached the "
                "model and came back empty, which is a failure rather than an "
                "abstention: an empty answer recorded as one an agent gave "
                "would put silence on the record as a decision."
            )
        return text


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
    if "maximum number of turns" in detail:
        return ProviderUnavailable(
            "the Claude Agent SDK stopped at its turn limit before producing "
            "any text. Nothing was recorded. This is the provider giving up, "
            "not the agent declining to answer."
        )
    if "session limit" in detail or "usage limit" in detail:
        # The scarce resource on a subscription is allowance, and running out
        # of it is an ordinary operating state -- the company will meet it far
        # more often than it meets a bug. It says when the limit resets,
        # because "try later" without a time is advice nobody can act on.
        return ProviderUnavailable(
            f"the subscription allowance is exhausted: {detail.strip()}. Work "
            "already recorded is unaffected; rerun after it resets."
        )
    return ProviderUnavailable(f"the Claude Agent SDK could not complete the call: {detail}")
