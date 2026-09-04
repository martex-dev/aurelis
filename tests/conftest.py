"""Shared fixtures.

Every test gets its own workspace in a temporary directory, its own database,
and a frozen clock. Nothing touches the network, no credentials are read, and
the mock provider answers every model call — which is what makes the whole
suite free to run and deterministic enough to assert on.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.platform.llm.providers import MockProvider
from aurelis.runtime import Runtime


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime(2026, 9, 4, 9, 0, tzinfo=dt.UTC))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        home=tmp_path,
        provider="mock",
        cache_models=True,
        strict_integrity=True,
        company_budget_usd="10",
        company_budget_tokens=1_000_000,
    )


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def runtime(
    settings: Settings, clock: FrozenClock, provider: MockProvider
) -> Iterator[Runtime]:
    """A fully wired, initialised runtime on a throwaway workspace."""
    built = Runtime.build(settings, clock=clock, provider=provider)
    built.initialise()
    try:
        yield built
    finally:
        built.close()


@pytest.fixture
def uninitialised(
    settings: Settings, clock: FrozenClock, provider: MockProvider
) -> Iterator[Runtime]:
    """A runtime whose schema has not been created.

    Used to prove that ``aurelis doctor`` reports an empty workspace as a
    problem rather than crashing on it.
    """
    built = Runtime.build(settings, clock=clock, provider=provider)
    try:
        yield built
    finally:
        built.close()
