"""Model access behind one provider-neutral interface."""

from aurelis.platform.llm.cache import CacheStats, CachingProvider
from aurelis.platform.llm.factory import KNOWN_PROVIDERS, build_provider, raw_provider
from aurelis.platform.llm.pricing import PRICE_TABLE_VERSION, price_for, usd_for
from aurelis.platform.llm.providers import (
    Availability,
    MockProvider,
    ModelProvider,
    UnavailableProvider,
)
from aurelis.platform.llm.types import LlmRequest, LlmResponse, Message, ModelRef, Usage

__all__ = [
    "KNOWN_PROVIDERS",
    "PRICE_TABLE_VERSION",
    "Availability",
    "CacheStats",
    "CachingProvider",
    "LlmRequest",
    "LlmResponse",
    "Message",
    "MockProvider",
    "ModelProvider",
    "ModelRef",
    "UnavailableProvider",
    "Usage",
    "build_provider",
    "price_for",
    "raw_provider",
    "usd_for",
]
