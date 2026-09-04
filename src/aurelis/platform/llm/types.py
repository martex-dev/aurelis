"""The vocabulary of a model call.

Provider-neutral by design: the same request runs against the mock provider in
CI, the Claude subscription in development, and a metered API when there is a
budget, and nothing above this layer knows which.

**Model identifiers are pinned to exact versions.** An alias that silently
moved would make every cached response unreproducible while the cache key
stayed the same — the cache would keep serving answers from a model that no
longer exists, and no test would notice.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from aurelis.core.canonical import sha256_of
from aurelis.core.enums import ModelTier

__all__ = ["LlmRequest", "LlmResponse", "Message", "ModelRef", "Usage"]

Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class ModelRef:
    """A pinned model, and how hard it is allowed to think."""

    provider: str
    model: str
    tier: ModelTier = ModelTier.MID
    max_tokens: int = 2048
    temperature: Decimal | None = None
    """``None`` means the provider default. A Decimal rather than a float so it
    can enter a cache key without the value differing across machines."""

    def key(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    """One completion request.

    ``actor`` and ``task_ref`` are carried so the model-call record can be
    joined to the work that caused it. "What did this finding cost to produce?"
    has to be answerable end to end, and it cannot be reconstructed later from
    logs nobody kept.
    """

    model: ModelRef
    system: str
    messages: tuple[Message, ...]
    actor: str = "system"
    task_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def cache_key(self) -> str:
        """Hash of everything that could change the answer.

        ``actor``, ``task_ref`` and ``metadata`` are excluded: two agents
        asking the identical question of the identical model deserve the same
        cached answer, and including who asked would make the cache useless.
        """
        return sha256_of(
            {
                "provider": self.model.provider,
                "model": self.model.model,
                "max_tokens": self.model.max_tokens,
                "temperature": self.model.temperature,
                "system": self.system,
                "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            }
        )


@dataclass(frozen=True, slots=True)
class Usage:
    """What a call consumed."""

    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass(frozen=True, slots=True)
class LlmResponse:
    """What came back.

    ``usd`` is what the provider says this cost. Under a subscription it is
    zero, and that is a true statement about marginal cost rather than a
    missing value — the scarce resource there is tokens, which are recorded
    either way.
    """

    text: str
    usage: Usage
    model: ModelRef
    usd: Decimal = Decimal("0")
    cache_hit: bool = False
    latency_ms: int = 0
    stop_reason: str = "end_turn"
    created_at: dt.datetime | None = None

    @property
    def digest(self) -> str:
        return sha256_of(self.text.encode("utf-8"))
