"""Model access: the mock provider, the cache, and call accounting."""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.core.enums import EventKind, ModelTier
from aurelis.core.errors import ConfigurationError, ProviderUnavailable
from aurelis.platform.db.tables import ModelCall
from aurelis.platform.llm.factory import raw_provider
from aurelis.platform.llm.pricing import PRICES, price_for, usd_for
from aurelis.platform.llm.providers import MockProvider, UnavailableProvider
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef
from aurelis.runtime import Runtime

MODEL = ModelRef(provider="mock", model="mock-1", tier=ModelTier.LOW, max_tokens=256)


def _request(
    question: str = "what is the state of the record?", actor: str = "AG-0001"
) -> LlmRequest:
    return LlmRequest(
        model=MODEL,
        system="You are a test participant.",
        messages=(Message("user", question),),
        actor=actor,
    )


# ------------------------------------------------------------------- pricing


def test_unpriced_model_raises_rather_than_assuming_free(runtime: Runtime) -> None:
    """A silent zero would make an unpriced model look free to a budget check."""
    with pytest.raises(KeyError, match="no price recorded"):
        price_for("claude-does-not-exist")


def test_prices_are_decimal_not_float() -> None:
    for price in PRICES.values():
        assert isinstance(price.input_per_mtok, Decimal)
        assert isinstance(price.output_per_mtok, Decimal)


def test_cost_is_per_million_tokens() -> None:
    assert usd_for("claude-sonnet-5", 1_000_000, 0) == Decimal("3")
    assert usd_for("claude-sonnet-5", 0, 1_000_000) == Decimal("15")


def test_mock_is_priced_at_zero_explicitly() -> None:
    """Priced rather than absent, so a mock run produces a real cost row of 0."""
    assert usd_for("mock-1", 10_000, 10_000) == Decimal("0")


# ---------------------------------------------------------------------- mock


def test_mock_is_deterministic() -> None:
    provider = MockProvider()
    first = provider.complete(_request())
    second = provider.complete(_request())
    assert first.text == second.text


def test_mock_output_is_visibly_a_mock() -> None:
    """It must never be mistaken for a real answer in a transcript."""
    assert MockProvider().complete(_request()).text.startswith("[mock:")


def test_scripted_replies_come_back_in_order() -> None:
    provider = MockProvider(scripted=["first", "second"])
    assert provider.complete(_request()).text == "first"
    assert provider.complete(_request()).text == "second"


def test_responder_sees_the_request() -> None:
    provider = MockProvider(responder=lambda r: f"answering {r.actor}")
    assert provider.complete(_request(actor="AG-0007")).text == "answering AG-0007"


def test_mock_reports_available_with_no_credentials() -> None:
    state = MockProvider().availability()
    assert state.available
    assert "no cost" in state.detail


# --------------------------------------------------------------- cache keys


def test_identical_requests_share_a_cache_key() -> None:
    assert _request().cache_key() == _request().cache_key()


def test_different_prompts_get_different_keys() -> None:
    assert _request("a").cache_key() != _request("b").cache_key()


def test_who_asked_does_not_affect_the_cache_key() -> None:
    """Two agents asking the same question deserve the same cached answer."""
    assert _request(actor="AG-0001").cache_key() == _request(actor="AG-0002").cache_key()


def test_model_version_is_part_of_the_key() -> None:
    """An alias that moved would keep the key stable while the model changed."""
    other = LlmRequest(
        model=ModelRef(provider="mock", model="mock-2", tier=ModelTier.LOW, max_tokens=256),
        system="You are a test participant.",
        messages=(Message("user", "what is the state of the record?"),),
    )
    assert other.cache_key() != _request().cache_key()


# --------------------------------------------------------------- the cache


def test_second_identical_call_is_served_from_cache(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        first = runtime.provider.complete(session, _request())
        second = runtime.provider.complete(session, _request())

    assert not first.cache_hit
    assert second.cache_hit
    assert second.text == first.text


def test_a_cache_hit_costs_nothing(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.provider.complete(session, _request())
        hit = runtime.provider.complete(session, _request())
    assert hit.usd == 0
    assert hit.usage.total == 0


def test_the_underlying_provider_is_only_called_once(
    runtime: Runtime, provider: MockProvider
) -> None:
    with runtime.database.session() as session:
        runtime.provider.complete(session, _request())
        runtime.provider.complete(session, _request())
    assert len(provider.calls) == 1


def test_cache_hits_are_still_recorded(runtime: Runtime) -> None:
    """The hit rate is one of the few cost levers measurable directly."""
    with runtime.database.session() as session:
        runtime.provider.complete(session, _request())
        runtime.provider.complete(session, _request())
        stats = runtime.provider.stats(session)
    assert stats.calls == 2
    assert stats.hits == 1
    assert stats.hit_rate == 0.5


def test_every_call_writes_a_record(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        runtime.provider.complete(session, _request())
        row = session.execute(sa.select(ModelCall)).scalars().one()
    assert row.actor == "AG-0001"
    assert row.model == "mock-1"
    assert row.response_hash is not None


def test_calls_append_to_the_ledger(runtime: Runtime) -> None:
    with runtime.database.session() as session:
        before = runtime.ledger.count(session)
        runtime.provider.complete(session, _request())
        runtime.provider.complete(session, _request())
        fresh = runtime.ledger.tail(session, runtime.ledger.count(session) - before)
        kinds = [e.kind for e in fresh]

    assert EventKind.MODEL_CALLED.value in kinds
    assert EventKind.MODEL_CACHE_HIT.value in kinds


def test_disabling_the_cache_still_records(runtime: Runtime, provider: MockProvider) -> None:
    """Accounting is not optional, even when caching is off."""
    from aurelis.platform.llm.cache import CachingProvider

    uncached = CachingProvider(
        provider, runtime.artifacts, ledger=runtime.ledger, clock=runtime.clock, enabled=False
    )
    with runtime.database.session() as session:
        uncached.complete(session, _request())
        uncached.complete(session, _request())
        stats = uncached.stats(session)
    assert stats.calls == 2
    assert stats.hits == 0
    assert len(provider.calls) == 2


# ------------------------------------------------------------------- factory


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="unknown provider"):
        raw_provider("telepathy")


def test_missing_optional_provider_reports_rather_than_crashing() -> None:
    """doctor must be able to describe the situation, not fail to start."""
    provider = raw_provider("anthropic_api")
    state = provider.availability()
    if not state.available:
        assert isinstance(provider, UnavailableProvider)
        with pytest.raises(ProviderUnavailable):
            provider.complete(_request())
