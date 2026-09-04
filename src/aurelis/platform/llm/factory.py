"""Choosing a provider from configuration.

A provider that cannot run is returned as an ``UnavailableProvider`` rather
than raised at construction. That way ``aurelis doctor`` can report the whole
picture — what is configured, what is installed, what is missing — instead of
the process failing to start on the first missing optional dependency.
"""

from __future__ import annotations

from aurelis.core.config import Settings
from aurelis.core.errors import ConfigurationError
from aurelis.platform.artifacts.store import ArtifactStore
from aurelis.platform.clock_default import default_clock
from aurelis.platform.ledger.ledger import Ledger
from aurelis.platform.llm.cache import CachingProvider
from aurelis.platform.llm.providers import MockProvider, ModelProvider, UnavailableProvider

__all__ = ["KNOWN_PROVIDERS", "build_provider", "raw_provider"]

KNOWN_PROVIDERS = ("mock", "agent_sdk", "anthropic_api")


def _if_available(name: str, provider: ModelProvider) -> ModelProvider:
    """Return the provider, or a placeholder describing why it cannot run."""
    state = provider.availability()
    return provider if state.available else UnavailableProvider(name, state.detail)


def raw_provider(name: str) -> ModelProvider:
    """Build an uncached provider by name."""
    if name == "mock":
        return MockProvider()
    if name == "agent_sdk":
        from aurelis.platform.llm.agent_sdk import AgentSdkProvider

        return _if_available(name, AgentSdkProvider())
    if name == "anthropic_api":
        from aurelis.platform.llm.anthropic_api import AnthropicApiProvider

        return _if_available(name, AnthropicApiProvider())
    raise ConfigurationError(
        f"unknown provider {name!r}; expected one of {', '.join(KNOWN_PROVIDERS)}"
    )


def build_provider(
    settings: Settings,
    store: ArtifactStore,
    *,
    ledger: Ledger | None = None,
    inner: ModelProvider | None = None,
) -> CachingProvider:
    """The provider the company actually uses: configured, then wrapped.

    Always wrapped, even with caching disabled, because the wrapper is also
    what records every call. Accounting is not optional.
    """
    clock = default_clock()
    return CachingProvider(
        inner or raw_provider(settings.provider),
        store,
        ledger=ledger or Ledger(clock),
        clock=clock,
        enabled=settings.cache_models,
    )
