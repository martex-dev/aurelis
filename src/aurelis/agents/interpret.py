"""Asking a model to interpret, and checking that it only did that.

One function, because the rule it enforces is the one that separates a
research organization from a very articulate opinion generator:

    **An agent may only state figures it was shown.**

The subtlety that makes this worth centralising: the set of permitted numerals
must be derived from *exactly* the material that was rendered into the prompt.
Building the prompt from one structure and validating against another is an
easy mistake — it was made twice while writing M2 — and it fails in the worst
possible direction, rejecting honest output while letting invented figures
through whenever the two structures happen to diverge.

Here the material is rendered and validated from the same object, so the two
cannot drift.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from aurelis.core.enums import ModelTier
from aurelis.platform.budget.ledger import Spend
from aurelis.platform.llm.types import LlmRequest, LlmResponse, Message, ModelRef

if TYPE_CHECKING:
    from aurelis.agents.loop import AgentContext

__all__ = [
    "Interpretation",
    "UnsourcedFigures",
    "allowed_figures",
    "interpret",
    "interpret_as",
    "render_material",
    "unsourced_numerals",
]

#: Numerals that may appear in prose without being a claim about the data.
#: Deliberately tiny: small counts and ordinals are unavoidable in English
#: ("two things stand out"), and everything else must be sourced.
_FREE_NUMERALS = frozenset({"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"})

_NUMERAL = re.compile(r"-?\d+(?:[.,]\d+)*%?")


def unsourced_numerals(text: str, allowed: set[str]) -> list[str]:
    """Numerals in ``text`` that do not appear in the measurements.

    The check is deliberately literal: a figure is either one the tools
    produced or it is not. Matching "approximately" would defeat the purpose,
    since a model that rounds 1.47 to 1.5 has stated a number nothing
    supports.
    """
    found: list[str] = []
    for match in _NUMERAL.finditer(text):
        token = match.group(0)
        bare = token.rstrip("%").replace(",", "")
        if bare in _FREE_NUMERALS or bare in allowed:
            continue
        # Tolerate a trailing zero difference: "0.50" cites "0.5".
        if bare.rstrip("0").rstrip(".") in {a.rstrip("0").rstrip(".") for a in allowed}:
            continue
        found.append(token)
    return found


def allowed_figures(*payloads: dict[str, Any]) -> set[str]:
    """Every numeric token the agent was actually shown."""
    allowed: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for match in _NUMERAL.finditer(value):
                allowed.add(match.group(0).rstrip("%").replace(",", ""))
        elif isinstance(value, (int, float)):
            allowed.add(str(value))

    for payload in payloads:
        walk(payload)
    return allowed



class UnsourcedFigures(ValueError):
    """The model stated a number nothing it was shown supports."""

    def __init__(self, invented: list[str], shown: int) -> None:
        super().__init__(
            f"output cites {len(invented)} figure(s) not present in the "
            f"{shown} value(s) supplied: {', '.join(invented[:5])}. "
            "Agents interpret; software computes."
        )
        self.invented = invented


class Interpretation:
    """A validated model response and what it cost."""

    __slots__ = ("response", "text")

    def __init__(self, response: LlmResponse) -> None:
        self.response = response
        self.text = response.text.strip()

    @property
    def spend(self) -> Spend:
        return Spend(self.response.usd, self.response.usage.total)


def render_material(material: dict[str, Any]) -> str:
    """Render the material an agent is being shown, deterministically."""
    lines: list[str] = []
    for section, payload in material.items():
        lines.append(f"{section.replace('_', ' ').title()}:")
        if isinstance(payload, dict):
            lines += [f"  {key}: {value}" for key, value in sorted(payload.items())]
        elif isinstance(payload, list):
            lines += [f"  - {item}" for item in payload]
        else:
            lines.append(f"  {payload}")
        lines.append("")
    return "\n".join(lines).strip()


def interpret_as(
    provider: Any,
    session: Any,
    *,
    agent_ref: str,
    system: str,
    material: dict[str, Any],
    tier: ModelTier = ModelTier.MID,
    max_tokens: int = 400,
    task_ref: str | None = None,
    model: str = "mock-1",
) -> Interpretation:
    """Ask the model to interpret ``material`` as ``agent_ref``, and refuse
    anything else.

    Takes the provider and session directly rather than an ``AgentContext``,
    because a meeting turn is not a task and inventing one to satisfy a
    signature would put rows in the queue for work nobody dispatched.

    Raises :class:`UnsourcedFigures` if the response contains a numeral that
    does not appear in ``material``. The caller then fails the turn and the
    reason is recorded against the agent, which is the outcome an Agent
    Behavior Auditor needs to be able to sample for.
    """
    response = provider.complete(
        session,
        LlmRequest(
            model=ModelRef(
                provider=provider.name, model=model, tier=tier, max_tokens=max_tokens
            ),
            system=system,
            messages=(Message("user", render_material(material)),),
            actor=agent_ref,
            task_ref=task_ref,
        ),
    )

    permitted = allowed_figures(material)
    invented = unsourced_numerals(response.text, permitted)
    if invented:
        raise UnsourcedFigures(invented, len(permitted))
    return Interpretation(response)


def interpret(
    context: AgentContext,
    *,
    system: str,
    material: dict[str, Any],
    tier: ModelTier = ModelTier.MID,
    max_tokens: int = 400,
) -> Interpretation:
    """:func:`interpret_as`, bound to the agent whose turn is running."""
    return interpret_as(
        context.provider,
        context.session,
        agent_ref=context.agent.ref,
        system=system,
        material=material,
        tier=tier,
        max_tokens=max_tokens,
        task_ref=context.task.ref,
        model=str(context.task.payload.get("model", "mock-1")),
    )
