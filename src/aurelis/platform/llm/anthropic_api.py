"""Metered API access.

Used when there is a budget. Until then the subscription provider or the mock
does the work, and this stays unimported — the SDK is an optional dependency
and its absence is a reported state, not a crash.

Token counts come from the provider's own usage report, never from an
estimate, because these are the numbers a budget is enforced against.
"""

from __future__ import annotations

import os
import time

from aurelis.core.errors import ProviderUnavailable
from aurelis.platform.llm.pricing import usd_for
from aurelis.platform.llm.providers import Availability
from aurelis.platform.llm.types import LlmRequest, LlmResponse, Usage

__all__ = ["AnthropicApiProvider"]

_API_KEY_ENV = "ANTHROPIC_API_KEY"


class AnthropicApiProvider:
    """Direct Anthropic API access, billed per token."""

    name = "anthropic_api"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get(_API_KEY_ENV)
        self._client: object | None = None

    def availability(self) -> Availability:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return Availability(
                self.name,
                False,
                "the 'anthropic' package is not installed (pip install 'aurelis[api]')",
            )
        if not self._api_key:
            return Availability(
                self.name, False, f"{_API_KEY_ENV} is not set"
            )
        return Availability(self.name, True, "metered API access; every call costs money")

    def _ensure_client(self) -> object:
        if self._client is not None:
            return self._client
        state = self.availability()
        if not state.available:
            raise ProviderUnavailable(state.detail)
        import anthropic

        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(self, request: LlmRequest) -> LlmResponse:
        client = self._ensure_client()
        started = time.perf_counter()

        kwargs: dict[str, object] = {
            "model": request.model.model,
            "max_tokens": request.model.max_tokens,
            "system": request.system,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if request.model.temperature is not None:
            kwargs["temperature"] = float(request.model.temperature)

        message = client.messages.create(**kwargs)  # type: ignore[attr-defined]
        latency = int((time.perf_counter() - started) * 1000)

        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        usage = Usage(
            tokens_in=int(message.usage.input_tokens),
            tokens_out=int(message.usage.output_tokens),
        )
        return LlmResponse(
            text=text,
            usage=usage,
            model=request.model,
            usd=usd_for(request.model.model, usage.tokens_in, usage.tokens_out),
            latency_ms=latency,
            stop_reason=str(message.stop_reason or "end_turn"),
        )
