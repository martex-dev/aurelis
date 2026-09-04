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

import re
from typing import Any

from aurelis.agents.loop import AgentContext, TurnResult, register_handler
from aurelis.comms.tables import MessageKind
from aurelis.core.clock import parse_utc
from aurelis.core.enums import EventKind, ModelTier
from aurelis.core.ids import RefKind, uuid7
from aurelis.intel.tables import MarketObservation, ObservationKind
from aurelis.org.scopes import ReadView, ToolScope
from aurelis.platform.budget.ledger import Spend
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

__all__ = ["TASK_KIND", "unsourced_numerals"]

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

#: Numerals that may appear in prose without being a claim about the data.
#: Deliberately tiny: small counts and ordinals are unavoidable in English
#: ("two things stand out"), and everything else must be sourced.
_FREE_NUMERALS = frozenset({"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"})

_NUMERAL = re.compile(r"-?\d+(?:[.,]\d+)*%?")


def unsourced_numerals(text: str, allowed: set[str]) -> list[str]:
    """Numerals in ``text`` that do not appear in the measurements.

    The check is deliberately literal: a figure is either one the tools
    produced or it is not. Matching "approximately" would defeat the purpose,
    since a model that rounds 1.47 to 1.5 has stated a number nothing
    supports.
    """
    found: list[str] = []
    for match in _NUMERAL.finditer(text):
        token = match.group(0)
        bare = token.rstrip("%").replace(",", "")
        if bare in _FREE_NUMERALS or bare in allowed:
            continue
        # Tolerate a trailing zero difference: "0.50" cites "0.5".
        if bare.rstrip("0").rstrip(".") in {a.rstrip("0").rstrip(".") for a in allowed}:
            continue
        found.append(token)
    return found


def _allowed_figures(*payloads: dict[str, Any]) -> set[str]:
    """Every numeric token the agent was actually shown."""
    allowed: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for match in _NUMERAL.finditer(value):
                allowed.add(match.group(0).rstrip("%").replace(",", ""))
        elif isinstance(value, (int, float)):
            allowed.add(str(value))

    for payload in payloads:
        walk(payload)
    return allowed


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

    # 3. The model interprets, and only interprets.
    prompt = {
        "desk": desk,
        "symbol": bars["symbol"],
        "source": bars["source"],
        "is_live": bars["is_live"],
        "caveat": bars["caveat"],
        "measurements": measures,
    }
    response = context.provider.complete(
        context.session,
        LlmRequest(
            model=ModelRef(
                provider=context.provider.name,
                model=context.task.payload.get("model", "mock-1"),
                tier=ModelTier.LOW,
                max_tokens=400,
            ),
            system=_SYSTEM,
            messages=(Message("user", _render(prompt)),),
            actor=context.agent.ref,
            task_ref=context.task.ref,
        ),
    )

    allowed = _allowed_figures(measures, {"symbol": bars["symbol"]})
    invented = unsourced_numerals(response.text, allowed)
    if invented:
        # Not a warning. The turn fails, and the reason is recorded against the
        # agent -- an analyst that states unsupported figures is exactly what
        # the Agent Behavior Auditor is for.
        raise ValueError(
            f"briefing cites {len(invented)} figure(s) not present in the "
            f"measurements: {', '.join(invented[:5])}. Agents interpret; "
            "software computes."
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
            "interpretation": response.text,
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
            statement=response.text.strip(),
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
        body=response.text.strip(),
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
        spend=Spend(response.usd, response.usage.total),
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
