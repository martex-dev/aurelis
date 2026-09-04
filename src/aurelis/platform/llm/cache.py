"""Response caching, and the record of every model call.

Two jobs in one wrapper, because they share the same hook.

**Caching.** Keyed on the pinned model version plus the canonical hash of the
request. Identical questions cost once. This is the reason model ids are
pinned rather than aliased: an alias that moved would keep the cache key stable
while the model behind it changed, and the cache would quietly serve answers
from a model that no longer exists.

**Recording.** Every call is written to ``model_calls``, cache hits included.
A hit costs nothing and is still recorded, because the cache hit rate is one of
the few cost levers that can be measured directly rather than estimated.

The cache stores responses as artifacts. That gets immutability, deduplication
and content-addressing for free, and means a cached answer is citable in
exactly the same way as any other artifact.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import canonical_json
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import uuid7
from aurelis.platform.artifacts.store import ArtifactStore
from aurelis.platform.db.tables import ModelCall
from aurelis.platform.ledger.ledger import Ledger
from aurelis.platform.llm.providers import Availability, ModelProvider
from aurelis.platform.llm.types import LlmRequest, LlmResponse, Usage

__all__ = ["CachingProvider", "CacheStats"]

_CACHE_KIND = "llm_response"


@dataclass(frozen=True)
class CacheStats:
    calls: int
    hits: int

    @property
    def hit_rate(self) -> float:
        return self.hits / self.calls if self.calls else 0.0


class CachingProvider:
    """Wraps any provider with a response cache and full call accounting."""

    def __init__(
        self,
        inner: ModelProvider,
        store: ArtifactStore,
        *,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
        enabled: bool = True,
    ) -> None:
        self._inner = inner
        self._store = store
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)
        self._enabled = enabled
        self.name = inner.name

    def availability(self) -> Availability:
        return self._inner.availability()

    def complete(self, session: Session, request: LlmRequest) -> LlmResponse:
        """Answer ``request``, from cache when possible, recording either way.

        Takes a session because the call record and the events describing it
        belong in the caller's transaction — the same reason the queue lives in
        the database.
        """
        key = request.cache_key()
        started = time.perf_counter()

        if self._enabled:
            cached = self._lookup(session, key)
            if cached is not None:
                latency = int((time.perf_counter() - started) * 1000)
                response = LlmResponse(
                    text=cached,
                    usage=Usage(),
                    model=request.model,
                    usd=Decimal("0"),
                    cache_hit=True,
                    latency_ms=latency,
                )
                self._record(session, request, response, key, cache_hit=True)
                return response

        response = self._inner.complete(request)
        self._record(session, request, response, key, cache_hit=False)
        return response

    def _lookup(self, session: Session, key: str) -> str | None:
        """Find a stored response for this request hash.

        The artifact's digest is the hash of its *content*, not of the request,
        so the request hash is recovered from the stored body. A dedicated
        index arrives if this ever gets hot; at the volumes involved the
        model call itself dominates by four orders of magnitude.
        """
        row = session.execute(
            sa.select(ModelCall.response_hash)
            .where(
                ModelCall.request_hash == key,
                ModelCall.cache_hit.is_(False),
                ModelCall.outcome == "ok",
                ModelCall.response_hash.is_not(None),
            )
            .order_by(ModelCall.created_at)
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        try:
            payload = self._store.get(row)
        except (FileNotFoundError, ValueError):
            return None
        import json

        body = json.loads(payload.decode("utf-8"))
        text = body.get("text")
        return text if isinstance(text, str) else None

    def _record(
        self,
        session: Session,
        request: LlmRequest,
        response: LlmResponse,
        key: str,
        *,
        cache_hit: bool,
    ) -> ModelCall:
        moment = self._clock.now()
        response_digest = (
            self._store.put_json(
                session,
                {"request_hash": key, "model": request.model.model, "text": response.text},
                kind=_CACHE_KIND,
                produced_by=request.actor,
            ).digest
            if not cache_hit and self._enabled
            else self._response_digest(session, key)
        )

        call = ModelCall(
            call_id=uuid7(),
            actor=request.actor,
            task_ref=request.task_ref,
            provider=self._inner.name,
            model=request.model.model,
            tier=request.model.tier.value,
            request_hash=key,
            response_hash=response_digest,
            tokens_in=response.usage.tokens_in,
            tokens_out=response.usage.tokens_out,
            usd=response.usd,
            cache_hit=cache_hit,
            latency_ms=response.latency_ms,
            outcome="ok",
            created_at=moment,
        )
        session.add(call)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.MODEL_CACHE_HIT if cache_hit else EventKind.MODEL_CALLED,
            actor=request.actor or Actor.SYSTEM,
            subject=request.task_ref,
            payload={
                "provider": self._inner.name,
                "model": request.model.model,
                "tier": request.model.tier.value,
                "tokens_in": response.usage.tokens_in,
                "tokens_out": response.usage.tokens_out,
                "usd": str(response.usd),
                "cache_hit": cache_hit,
                "request_hash": key[:16],
            },
            at=moment,
        )
        return call

    def _response_digest(self, session: Session, key: str) -> str | None:
        return session.execute(
            sa.select(ModelCall.response_hash)
            .where(ModelCall.request_hash == key, ModelCall.response_hash.is_not(None))
            .limit(1)
        ).scalar_one_or_none()

    def stats(self, session: Session) -> CacheStats:
        calls, hits = session.execute(
            sa.select(
                sa.func.count(),
                sa.func.coalesce(sa.func.sum(sa.cast(ModelCall.cache_hit, sa.Integer)), 0),
            ).select_from(ModelCall)
        ).one()
        return CacheStats(calls=int(calls), hits=int(hits))


def describe_request(request: LlmRequest) -> str:
    """Human-readable one-liner, for logs and the station."""
    return canonical_json(
        {
            "model": request.model.key(),
            "actor": request.actor,
            "task": request.task_ref,
            "messages": len(request.messages),
        }
    )
