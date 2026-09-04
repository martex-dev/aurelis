"""Tools: the only way an agent affects anything outside itself.

A tool is a **bound capability** — a deterministic function, declared in a
registry, invoked through one gate that checks the agent's tool scope, records
the call with its cost, and appends to the ledger.

Two consequences worth stating.

**Agents compute nothing.** Every number an agent reports comes back from a
tool and carries the digest of the data it was derived from. This is the rule
that separates a research organization from a very articulate opinion
generator, and the mechanism is that there is no other way to get a number.

**A refused call is a recorded outcome, not an exception to swallow.** An agent
reaching for a tool its charters do not grant is precisely what an Agent
Behavior Auditor looks for, so the attempt is written down before the refusal
is raised.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from aurelis.agents.tables import ToolCall
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import PermissionDenied
from aurelis.core.ids import uuid7
from aurelis.org.scopes import ToolScope
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["ToolBox", "ToolResult", "ToolSpec", "register_tool", "registered_tools"]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool returned, and what it cost."""

    value: dict[str, Any]
    usd: Decimal = Decimal("0")
    detail: str = ""


ToolFn = Callable[[dict[str, Any]], ToolResult]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    scope: ToolScope
    name: str
    summary: str
    fn: ToolFn
    deterministic: bool = True


_TOOLS: dict[ToolScope, ToolSpec] = {}


def register_tool(
    scope: ToolScope, summary: str, *, deterministic: bool = True
) -> Callable[[ToolFn], ToolFn]:
    """Bind an implementation to a tool scope. One implementation per scope."""

    def decorate(fn: ToolFn) -> ToolFn:
        if scope in _TOOLS:
            raise ValueError(
                f"tool {scope} already has an implementation "
                f"({_TOOLS[scope].fn.__name__}); two would mean two answers to "
                "the same call"
            )
        _TOOLS[scope] = ToolSpec(scope, scope.value, summary, fn, deterministic)
        return fn

    return decorate


def registered_tools() -> frozenset[ToolScope]:
    return frozenset(_TOOLS)


class ToolBox:
    """The gate. Every tool call in the company goes through :meth:`invoke`."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def available_to(self, permitted: frozenset[ToolScope]) -> tuple[ToolSpec, ...]:
        """The tools an agent can actually call: granted *and* implemented."""
        return tuple(spec for scope, spec in sorted(_TOOLS.items()) if scope in permitted)

    def invoke(
        self,
        session: Session,
        *,
        agent_ref: str,
        scope: ToolScope,
        arguments: dict[str, Any] | None = None,
        permitted: frozenset[ToolScope],
        task_ref: str | None = None,
    ) -> ToolResult:
        """Check the scope, run the tool, record the call either way."""
        args = dict(arguments or {})
        moment = self._clock.now()

        if scope not in permitted:
            self._record(
                session,
                agent_ref=agent_ref,
                task_ref=task_ref,
                scope=scope,
                arguments=args,
                outcome="refused",
                detail="no charter this agent covers grants this tool",
                duration_ms=0,
                usd=Decimal("0"),
                at=moment,
            )
            raise PermissionDenied(agent_ref, f"use {scope.value}", task_ref or "-")

        spec = _TOOLS.get(scope)
        if spec is None:
            self._record(
                session,
                agent_ref=agent_ref,
                task_ref=task_ref,
                scope=scope,
                arguments=args,
                outcome="failed",
                detail="granted but not implemented at this milestone",
                duration_ms=0,
                usd=Decimal("0"),
                at=moment,
            )
            raise NotImplementedError(
                f"tool {scope.value} is granted to this agent but has no "
                "implementation yet; it lands with the layer that owns it"
            )

        started = time.perf_counter()
        try:
            result = spec.fn(args)
        except Exception as error:
            self._record(
                session,
                agent_ref=agent_ref,
                task_ref=task_ref,
                scope=scope,
                arguments=args,
                outcome="failed",
                detail=f"{type(error).__name__}: {error}",
                duration_ms=int((time.perf_counter() - started) * 1000),
                usd=Decimal("0"),
                at=moment,
            )
            raise

        self._record(
            session,
            agent_ref=agent_ref,
            task_ref=task_ref,
            scope=scope,
            arguments=args,
            outcome="ok",
            detail=result.detail,
            duration_ms=int((time.perf_counter() - started) * 1000),
            usd=result.usd,
            at=moment,
        )
        return result

    def _record(
        self,
        session: Session,
        *,
        agent_ref: str,
        task_ref: str | None,
        scope: ToolScope,
        arguments: dict[str, Any],
        outcome: str,
        detail: str,
        duration_ms: int,
        usd: Decimal,
        at: dt.datetime,
    ) -> None:
        session.add(
            ToolCall(
                call_id=uuid7(),
                agent_ref=agent_ref,
                task_ref=task_ref,
                tool=scope.value,
                arguments=arguments,
                outcome=outcome,
                detail=detail,
                duration_ms=duration_ms,
                usd=str(usd),
                created_at=at,
            )
        )
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.TOOL_CALLED,
            actor=agent_ref,
            subject=task_ref,
            payload={
                "tool": scope.value,
                "outcome": outcome,
                "duration_ms": duration_ms,
                "usd": str(usd),
                "detail": detail[:200],
            },
            at=at,
        )


# ------------------------------------------------------------ M1 tool set


@register_tool(ToolScope.DATA_OHLCV, "Closed OHLCV bars for a desk symbol, with a data digest")
def _data_ohlcv(arguments: dict[str, Any]) -> ToolResult:
    from aurelis.intel.sources import snapshot_for

    desk = str(arguments.get("desk", "crypto"))
    symbol = arguments.get("symbol")
    limit = int(arguments.get("limit", 48))
    snapshot = snapshot_for(desk, symbol if symbol is None else str(symbol), limit=limit)
    return ToolResult(
        value=snapshot,
        detail=f"{len(snapshot['bars'])} bars from {snapshot['source']}",
    )


@register_tool(ToolScope.ENGINE_FEATURES, "Summary statistics over a bar series")
def _engine_features(arguments: dict[str, Any]) -> ToolResult:
    """Deterministic descriptive measures.

    Exactly the sort of thing that must never be asked of a language model: it
    is arithmetic, it is cheap, and a model's answer could not be reproduced.
    """
    from aurelis.intel.features import describe_bars

    bars = arguments.get("bars")
    if not isinstance(bars, list) or not bars:
        raise ValueError("features requires a non-empty 'bars' list from data.ohlcv")
    measures = describe_bars(bars)
    return ToolResult(value=measures, detail=f"{len(measures)} measures over {len(bars)} bars")
