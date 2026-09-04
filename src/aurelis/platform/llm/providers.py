"""The provider protocol, and the mock that makes the company free to run.

Three implementations sit behind one interface: ``mock`` (offline,
deterministic, free), ``agent_sdk`` (the Claude subscription), and
``anthropic_api`` (metered). Switching between them is a config change, and
nothing above this layer knows which is active.

The mock is not a stub. It is how the whole company is developed and tested:
every test in CI runs against it, which is what makes a hundred agents
affordable to build.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from aurelis.core.errors import ProviderUnavailable
from aurelis.platform.llm.pricing import usd_for
from aurelis.platform.llm.types import LlmRequest, LlmResponse, Usage

__all__ = ["Availability", "MockProvider", "ModelProvider"]


@dataclass(frozen=True)
class Availability:
    """Whether a provider can actually be used, and why not."""

    name: str
    available: bool
    detail: str


@runtime_checkable
class ModelProvider(Protocol):
    """Anything that can answer a completion request."""

    name: str

    def complete(self, request: LlmRequest) -> LlmResponse: ...

    def availability(self) -> Availability: ...


def _estimate_tokens(text: str) -> int:
    """Rough token count for accounting under providers that report none.

    Four characters per token is the usual English approximation. It is an
    estimate and is labelled as one wherever it surfaces — a budget that
    silently treated an estimate as a measurement would drift.
    """
    return max(1, len(text) // 4)


class MockProvider:
    """Deterministic, offline, free.

    Two modes, and both are useful:

    * **scripted** — replies are queued in order, or supplied by a function of
      the request. This is how a test asserts what a particular agent said.
    * **echo** — a stable, content-derived reply. Enough for exercising
      plumbing without writing a script for every call.

    Determinism is the point. The same request produces the same answer, so a
    whole company-day replays identically and a test that passes once passes
    again.
    """

    name = "mock"

    def __init__(
        self,
        *,
        responder: Callable[[LlmRequest], str] | None = None,
        scripted: list[str] | None = None,
        model_id: str = "mock-1",
    ) -> None:
        self._responder = responder
        self._script: deque[str] = deque(scripted or [])
        self._model_id = model_id
        self.calls: list[LlmRequest] = []

    def push(self, *replies: str) -> None:
        """Queue further scripted replies."""
        self._script.extend(replies)

    def complete(self, request: LlmRequest) -> LlmResponse:
        started = time.perf_counter()
        self.calls.append(request)

        if self._responder is not None:
            text = self._responder(request)
        elif self._script:
            text = self._script.popleft()
        else:
            # Content-derived so it is stable across runs, and visibly a mock
            # so it can never be mistaken for a real answer in a transcript.
            text = f"[mock:{request.cache_key()[:8]}] {request.messages[-1].content[:160]}"

        tokens_in = _estimate_tokens(request.system) + sum(
            _estimate_tokens(m.content) for m in request.messages
        )
        tokens_out = _estimate_tokens(text)
        return LlmResponse(
            text=text,
            usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out),
            model=request.model,
            usd=usd_for(self._model_id, tokens_in, tokens_out),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def availability(self) -> Availability:
        return Availability(
            self.name, True, "offline deterministic provider; no credentials, no cost"
        )


class UnavailableProvider:
    """A named provider that is not installed or not configured.

    Returned by the factory instead of raising at import time, so ``aurelis
    doctor`` can report the situation clearly rather than the process failing
    to start. Calling it raises.
    """

    def __init__(self, name: str, detail: str) -> None:
        self.name = name
        self._detail = detail

    def complete(self, request: LlmRequest) -> LlmResponse:
        raise ProviderUnavailable(f"provider {self.name!r} is unavailable: {self._detail}")

    def availability(self) -> Availability:
        return Availability(self.name, False, self._detail)


def zero_cost() -> Decimal:
    """Explicit zero, for providers billed by subscription rather than usage."""
    return Decimal("0")
