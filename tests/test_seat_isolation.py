"""The seat has no tools, and the guard is not a list of names.

Every measurement this company takes of an agent — the authoring space, the
critic's scenario suite, the conformance rehearsal — assumes the agent knew
only what its material told it. The first campaign run against a real model
through the Claude Agent SDK broke that assumption completely:
``allowed_tools=[]`` reads as *no restriction*, not as *nothing allowed*, and
the model answered a design question by running ``Grep`` over this repository.
It read ``aurelis/authoring/standin.py`` — the module that scripts what a
stand-in is supposed to answer — and ``tests/test_campaign.py``, and then
replied.

That is not a model reasoning about a market. It is a model finding the answer
key, and any seat score taken that way measures nothing.

The fix is a callback that denies every tool, and these tests pin it. They are
deliberately about *configuration*, not about a call: no network, no
credentials, no spawned process.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

pytest.importorskip(
    "claude_agent_sdk",
    reason="the subscription provider is an optional extra",
)


def _request() -> LlmRequest:
    return LlmRequest(
        model=ModelRef(provider="agent_sdk", model="claude-opus-5"),
        system="Answer with one key.",
        messages=(Message(role="user", content="Which lookback?"),),
    )


def _provider() -> object:
    from aurelis.platform.llm.agent_sdk import AgentSdkProvider

    return AgentSdkProvider()


def test_every_tool_is_denied_whatever_it_is_called() -> None:
    """The guard cannot be a list, because the reachable surface is not ours.

    The first tool actually refused in practice was
    ``mcp__claude_ai_Remote_Desktop_Commander__list_directory`` — an MCP server
    belonging to the person running the command, inherited by the process the
    SDK spawns. No allow-list in this repository could have named it.
    """
    provider = _provider()
    for tool in ("Grep", "Read", "Bash", "mcp__someone_elses_server__do_thing"):
        result = asyncio.run(provider.refuse_tool(tool, {}, None))  # type: ignore[attr-defined]
        assert result.behavior == "deny", f"{tool} was not denied"
        assert "no tools" in result.message


def test_a_refused_tool_is_recorded_rather_than_silently_blocked() -> None:
    """An agent that keeps reaching for a lookup is saying its material is not
    enough. That is worth seeing."""
    provider = _provider()
    asyncio.run(provider.refuse_tool("Grep", {}, None))  # type: ignore[attr-defined]
    asyncio.run(provider.refuse_tool("Read", {}, None))  # type: ignore[attr-defined]
    assert provider.refused_tools == ["Grep", "Read"]  # type: ignore[attr-defined]


def test_the_seat_carries_no_mcp_servers() -> None:
    """The operator's own connectors must not follow a seat in.

    ``strict_mcp_config`` is what makes the empty mapping mean *none* rather
    than *none in addition to whatever is configured*.
    """
    options = _provider().options(_request())  # type: ignore[attr-defined]
    assert options.mcp_servers == {}
    assert options.strict_mcp_config is True


def test_the_seat_does_not_run_inside_this_repository() -> None:
    """Not the security boundary — the deny callback is that — but a seat whose
    working directory is the repository holding the tests it is scored by is
    one bad configuration away from reading them."""
    options = _provider().options(_request())  # type: ignore[attr-defined]
    cwd = Path(options.cwd).resolve()
    repository = Path(__file__).resolve().parent.parent
    assert repository not in cwd.parents and cwd != repository
    assert not list(cwd.glob("**/*.py")), "the seat's directory holds no code"


def test_the_deny_callback_is_wired_not_merely_defined() -> None:
    """A guard that exists and is not passed to the SDK is not a guard."""
    provider = _provider()
    options = provider.options(_request())  # type: ignore[attr-defined]
    wired = options.can_use_tool
    assert wired is not None, "no permission callback was passed to the SDK"
    # Bound methods compare equal but are not identical, so compare the
    # function and the instance it is bound to.
    assert wired.__func__ is type(provider).refuse_tool
    assert wired.__self__ is provider


def test_the_named_disallow_list_is_documentation_and_says_so() -> None:
    """Kept so an operator reading the configuration sees the intent, and so
    the seat fails closed if a future SDK stops calling the callback. It is
    not what the tests above rely on."""
    from aurelis.platform.llm.agent_sdk import _NO_TOOLS

    options = _provider().options(_request())  # type: ignore[attr-defined]
    assert set(options.disallowed_tools) == set(_NO_TOOLS)
    assert "Grep" in _NO_TOOLS and "Read" in _NO_TOOLS
