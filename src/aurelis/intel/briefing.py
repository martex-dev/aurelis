"""The intelligence briefing: the company's first real work.

An analyst wakes on a scheduled task, looks at its desk, measures what it sees,
records an observation, and posts a briefing to the desk channel.

This is small on purpose, and every step is the shape every later handler will
take:

1. **Build a view.** Refused if the charters do not grant it.
2. **Call tools for the numbers.** ``data.ohlcv`` returns bars with a digest;
   ``engine.features`` measures them. The agent computes nothing itself.
3. **Ask the model to interpret** — and only to interpret. Its output is prose
   about numbers it was given, and a validator rejects any numeral that was not
   in the tool results.
4. **Record an observation**, carrying ``as_of``, ``observed_at``, the source
   and the data digest.
5. **Post a briefing** whose claims cite the observation.

Step 3's validator is the load-bearing part. It is the rule that separates a
research organization from a very articulate opinion generator, and it is
enforced here rather than requested in a prompt.
"""

from __future__ import annotations

from typing import Any

from aurelis.agents.interpret import interpret
from aurelis.agents.loop import AgentContext, TurnResult, register_handler
from aurelis.comms.tables import MessageKind
from aurelis.core.clock import parse_utc
from aurelis.core.enums import EventKind, ModelTier
from aurelis.core.ids import RefKind, uuid7
from aurelis.intel.tables import MarketObservation, ObservationKind
from aurelis.org.scopes import ReadView, ToolScope
from aurelis.platform.db.refs import allocate_ref

__all__ = ["TASK_KIND", "run_briefing"]

TASK_KIND = "intel.briefing"

_SYSTEM = """You are a market intelligence analyst at Aurelis, a quantitative \
research corporation.

You are given measurements that were computed by tools. Interpret them in two \
or three sentences: what the series looks like, and what would be worth \
investigating.

Hard rules:
- Use ONLY figures that appear in the measurements you were given. Never \
introduce a number of your own, and never round one into a different number.
- Describe what was observed. Do not predict, do not recommend a trade, and do \
not claim an edge exists.
- If the data is described as fixture or non-live, say so plainly."""

@register_handler(TASK_KIND)
def run_briefing(context: AgentContext) -> TurnResult:
    """Produce one desk briefing."""
    desk = context.agent.desk.value if context.agent.desk else "crypto"
    symbol = context.task.payload.get("symbol")
    limit = int(context.task.payload.get("bars", 48))

    # 1. The view. Refused outright if the charters do not grant it.
    context.view(ReadView.DESK_MARKET_SNAPSHOT, symbol=symbol)

    # 2. Tools produce every number. The agent produces none.
    bars = context.use(ToolScope.DATA_OHLCV, desk=desk, symbol=symbol, limit=limit).value
    measures = context.use(ToolScope.ENGINE_FEATURES, bars=bars["bars"]).value

    # 3. The model interprets, and only interprets. `interpret` renders the
    #    material and validates the answer against that same object, so the
    #    permitted figures cannot drift from what the agent was shown.
    material = {
        "desk": desk,
        "symbol": bars["symbol"],
        "source": bars["source"],
        "is_live": bars["is_live"],
        "caveat": bars["caveat"],
        "measurements": measures,
    }
    interpretation = interpret(
        context, system=_SYSTEM, material=material, tier=ModelTier.LOW
    )

    # 4. The observation, with its provenance.
    now = context.clock.now()
    as_of = parse_utc(bars["as_of"])
    ref = allocate_ref(context.session, RefKind.OBSERVATION)
    stored = context.artifacts.put_json(
        context.session,
        {
            "desk": desk,
            "symbol": bars["symbol"],
            "source": bars["source"],
            "data_digest": bars["data_digest"],
            "measurements": measures,
            "interpretation": interpretation.text,
        },
        kind="market_observation",
        produced_by=context.task.ref,
        actor=context.agent.ref,
    )

    context.session.add(
        MarketObservation(
            observation_id=uuid7(),
            ref=ref,
            author=context.agent.ref,
            desk=desk,
            symbol=bars["symbol"],
            kind=ObservationKind.PRICE_STRUCTURE.value,
            statement=interpretation.text,
            measures=measures,
            as_of=as_of,
            observed_at=max(now, as_of),
            source=bars["source"],
            data_digest=bars["data_digest"],
            artifact_digest=stored.digest,
            task_ref=context.task.ref,
            created_at=now,
        )
    )
    context.session.flush()

    context.ledger.append(
        context.session,
        kind=EventKind.OBSERVATION_RECORDED,
        actor=context.agent.ref,
        subject=ref,
        payload={
            "desk": desk,
            "symbol": bars["symbol"],
            "source": bars["source"],
            "artifact": stored.digest[:12],
            "data_digest": bars["data_digest"][:12],
        },
        at=now,
    )

    # 5. The briefing, citing the observation.
    context.comms.post(
        context.session,
        from_agent=context.agent.ref,
        kind=MessageKind.BRIEFING,
        channel_id=f"desk-{desk}",
        subject=f"{bars['symbol']} — {measures['bars']} bars to {bars['as_of'][:10]}",
        body=interpretation.text,
        claims=(
            f"change over window: {measures['change']}",
            f"return volatility: {measures['return_volatility']}",
        ),
        evidence_refs=(ref, stored.digest, bars["data_digest"]),
        desk=desk,
        task_ref=context.task.ref,
        at=now,
    )

    return TurnResult(
        summary=f"{context.agent.handle} briefed {desk} on {bars['symbol']}",
        artifact_digest=stored.digest,
        spend=interpretation.spend,
        produced={"observation": ref, "measures": measures},
    )


def _render(payload: dict[str, Any]) -> str:
    lines = [
        f"Desk: {payload['desk']}",
        f"Symbol: {payload['symbol']}",
        f"Source: {payload['source']} (live: {payload['is_live']})",
        f"Caveat: {payload['caveat']}",
        "",
        "Measurements:",
    ]
    lines += [f"  {key}: {value}" for key, value in sorted(payload["measurements"].items())]
    return "\n".join(lines)
