"""The seat where an agent turns a mined conjunction into a stated mechanism.

An agent is shown a co-occurrence the world model found — a trigger event kind,
how often it is followed by a second kind within a window, on which instruments
— and is asked whether it can state a mechanism: why the pattern would work,
who is on the other side, a direction and horizon for the move, a confidence,
and a decay model. If it cannot, it says so, and the conjunction stays a
conjunction. If it can, the mechanism is sealed and its predictions begin.

The prose is figure-checked. Nothing about the *count* of co-occurrences is a
reason the mechanism works — that is the observation that prompted the
question, and a mechanism whose only justification is "it happened often" is
data mining with a sentence attached. So the agent must give a *causal* reason,
and the seat cannot check causality; what it can do is require the reason and
require a decay model, and then let the out-of-sample predictions decide.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from aurelis.agents.interpret import (
    FIGURE_RULE,
    allowed_figures,
    render_material,
    unsourced_numerals,
)
from aurelis.core.enums import Actor, EventKind, ModelTier
from aurelis.mechanism.library import Mechanisms
from aurelis.mechanism.tables import Mechanism
from aurelis.platform.llm.routing import model_for
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef
from aurelis.world.store import CoOccurrence, World

__all__ = ["DISCOVERY_FORM", "SYSTEM", "MechanismProposal", "propose_mechanism", "seat_discovery"]

SYSTEM = (
    "You are a researcher at a quantitative company. The company has mined its "
    "event record and found that one kind of event is often followed by another "
    "within a window. A pattern that merely happens often is not an edge -- it "
    "is a coincidence in a search space with astronomically many conjunctions. "
    "It becomes a mechanism only if you can say WHY it should work: who is on "
    "the other side of the trade, what constraint or asymmetry makes them act, "
    "and why the edge persists rather than being competed away.\n\n"
    "State a mechanism only if you can give a causal reason. `nothing` is the "
    "right answer when the pattern is plausibly a coincidence. Whatever you "
    "state will be applied to every other occurrence as a sealed prediction and "
    "scored -- the count you were shown will not save a mechanism that does not "
    "actually predict."
)

DISCOVERY_FORM = (
    "State a mechanism for this pattern, or decline. Reply in exactly this form "
    "and nothing else:\n"
    "MECHANISM: <a short title>\n"
    "DIRECTION: up | down\n"
    "HORIZON: <hours ahead the move plays out, a whole number 1 to 168>\n"
    "CONFIDENCE: <a probability strictly above 0.5 and at most 1>\n"
    "WHY: <the causal reason it works>\n"
    "OTHER_SIDE: <who takes the losing side of the trade, and why>\n"
    "DECAY: <how crowded it can get and how fast it dies once others find it>\n\n"
    "Or, if you cannot give a causal reason: MECHANISM: nothing\n\n"
    f"{FIGURE_RULE}"
)

_FIELD = re.compile(
    r"^\s*(MECHANISM|DIRECTION|HORIZON|CONFIDENCE|WHY|OTHER_SIDE|DECAY)\s*:\s*(.*)$", re.I
)


class MechanismRefused(ValueError):
    """The reply could not be read, or cited a figure it was not shown."""


@dataclass(frozen=True, slots=True)
class MechanismProposal:
    title: str | None
    direction: str
    horizon: int
    confidence: Decimal
    why: str
    other_side: str
    decay: str

    @property
    def declined(self) -> bool:
        return self.title is None


def _parse(text: str) -> MechanismProposal:
    fields: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).upper()
            fields[current] = match.group(2).strip()
        elif current in ("WHY", "OTHER_SIDE", "DECAY") and line.strip():
            fields[current] = f"{fields[current]} {line.strip()}".strip()

    title = fields.get("MECHANISM", "").strip()
    if title.lower() == "nothing" or not title:
        return MechanismProposal(None, "up", 0, Decimal("1"), "", "", "")

    direction = fields.get("DIRECTION", "").strip().lower()
    if direction not in ("up", "down"):
        raise MechanismRefused(f"direction {direction or '<empty>'!r} is not up or down")
    try:
        horizon = int(fields.get("HORIZON", "").strip())
    except ValueError:
        raise MechanismRefused("horizon is not a whole number") from None
    if not 1 <= horizon <= 168:
        raise MechanismRefused(f"horizon {horizon} is outside 1..168")
    raw = fields.get("CONFIDENCE", "").strip().rstrip("%")
    try:
        confidence = Decimal(raw)
    except InvalidOperation:
        raise MechanismRefused(f"confidence {raw or '<empty>'!r} is not a number") from None
    if confidence > 1 and confidence <= 100:
        confidence = confidence / 100
    if not Decimal("0.5") < confidence <= 1:
        raise MechanismRefused(f"confidence {confidence} is not above 0.5 and at most 1")
    why = fields.get("WHY", "").strip()
    other = fields.get("OTHER_SIDE", "").strip()
    decay = fields.get("DECAY", "").strip()
    if len(why) <= 20:
        raise MechanismRefused("a mechanism of fewer than twenty characters is not a reason")
    if len(other) <= 10:
        raise MechanismRefused("a mechanism must name who is on the other side")
    if len(decay) <= 10:
        raise MechanismRefused("a mechanism without a decay model will be held too long")
    return MechanismProposal(
        title, direction, horizon, confidence.quantize(Decimal("0.01")), why, other, decay
    )


def _material(
    trigger_kind: str, second_kind: str, pairs: list[CoOccurrence], window_hours: int
) -> dict[str, Any]:
    by_instrument: dict[str, int] = {}
    for pair in pairs:
        by_instrument[pair.entity_key] = by_instrument.get(pair.entity_key, 0) + 1
    return {
        "pattern": {
            "trigger": trigger_kind,
            "then": second_kind,
            "within hours": window_hours,
            "occurrences": len(pairs),
            "instruments": len(by_instrument),
        },
        "by_instrument": {k: str(v) for k, v in sorted(by_instrument.items())},
        "note": (
            "This count is what the mining found. It is not evidence the pattern "
            "predicts anything; a causal reason is."
        ),
    }


def propose_mechanism(
    provider: Any,
    session: Session,
    mechanisms: Mechanisms,
    *,
    agent_ref: str,
    trigger_kind: str,
    second_kind: str,
    desk: str,
    window_hours: int = 24,
    tier: ModelTier = ModelTier.HIGH,
    identity: str = "",
    task_ref: str | None = None,
    ledger: Any = None,
    at: dt.datetime | None = None,
) -> Mechanism | None:
    """Show an agent a co-occurrence and seal the mechanism it states, or ``None``.

    The strongest instrument (the one with the most occurrences) is the training
    instance the mechanism is tagged as found on.
    """
    moment = at or (mechanisms._clock.now())  # noqa: SLF001 - same clock as the store
    pairs = World.co_occurrences(
        session,
        first_kind=trigger_kind,
        second_kind=second_kind,
        within=dt.timedelta(hours=window_hours),
    )
    if not pairs:
        return None
    material = _material(trigger_kind, second_kind, pairs, window_hours)
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair.entity_key] = counts.get(pair.entity_key, 0) + 1
    found_on = max(sorted(counts), key=lambda k: counts[k])
    found_event = next(p.first.digest for p in pairs if p.entity_key == found_on)

    system = f"{SYSTEM}\n\n{identity}" if identity else SYSTEM
    rendered = f"{render_material(material)}\n\n{DISCOVERY_FORM}"
    model_id = model_for(provider.name, tier)
    response = provider.complete(
        session,
        LlmRequest(
            model=ModelRef(provider=provider.name, model=model_id, tier=tier, max_tokens=500),
            system=system,
            messages=(Message("user", rendered),),
            actor=agent_ref,
            task_ref=task_ref,
        ),
    )
    proposal = _parse(response.text)
    if proposal.declined:
        if ledger is not None:
            ledger.append(
                session,
                kind=EventKind.MECHANISM_DECLINED,
                actor=agent_ref,
                subject=agent_ref,
                payload={"trigger": trigger_kind, "then": second_kind},
                at=moment,
            )
        return None
    permitted = allowed_figures(material, {"form": DISCOVERY_FORM})
    invented = unsourced_numerals(
        f"{proposal.why}\n{proposal.other_side}\n{proposal.decay}", permitted
    )
    if invented:
        raise MechanismRefused(
            f"the mechanism cites {len(invented)} figure(s) it was not shown: "
            f"{', '.join(invented[:5])}"
        )
    return mechanisms.state(
        session,
        agent_ref=agent_ref,
        title=proposal.title or "",
        trigger_kind=trigger_kind,
        desk=desk,
        horizon_hours=proposal.horizon,
        direction=proposal.direction,
        confidence=proposal.confidence,
        why=proposal.why,
        other_side=proposal.other_side,
        decay=proposal.decay,
        origin="invented",
        found_on_instrument=found_on,
        found_on_event=found_event[:16],
        model=f"{provider.name}:{model_id}",
        tokens=response.usage.total,
        usd=response.usd,
        at=moment,
    )


def seat_discovery(
    runtime: Any,
    *,
    agent_handle: str,
    trigger_kind: str = "price.volume_spike",
    second_kind: str = "price.range_break",
    desk: str = "crypto",
    window_hours: int = 24,
    at: dt.datetime | None = None,
) -> Mechanism | None:
    """Put a named agent in the discovery seat under a task, and generate the
    new mechanism's predictions immediately so its record can begin."""
    from aurelis.judgement.seat import identity_of
    from aurelis.mechanism.predictions import generate_predictions
    from aurelis.platform.db.refs import allocate_ref

    moment = at or runtime.clock.now()
    with runtime.database.session() as session:
        seated = runtime.roster.by_handle(session, agent_handle)
        task = runtime.queue.enqueue(
            session,
            kind="mechanism.discovery",
            assignee=seated.ref,
            payload={"trigger": trigger_kind, "then": second_kind},
            actor=Actor.SYSTEM,
            at=moment,
        )
        claimed = runtime.queue.claim(session, worker=seated.ref, at=moment)
        task_ref = claimed.ref if claimed is not None else task.ref
        mechanism = propose_mechanism(
            runtime.provider,
            session,
            runtime.mechanisms,
            agent_ref=seated.ref,
            trigger_kind=trigger_kind,
            second_kind=second_kind,
            desk=desk,
            window_hours=window_hours,
            tier=seated.authority.tier
            if seated.authority.tier is not ModelTier.NONE
            else ModelTier.HIGH,
            identity=identity_of(seated),
            task_ref=task_ref,
            ledger=runtime.ledger,
            at=moment,
        )
        if claimed is not None:
            digest = mechanism.seal if mechanism is not None else "0" * 64
            from aurelis.core.canonical import sha256_of

            runtime.queue.succeed(
                session,
                claimed,
                result_digest=digest if mechanism is not None else sha256_of({"declined": True}),
                at=moment,
            )
        if mechanism is not None:
            generate_predictions(
                session, mechanism, ledger=runtime.ledger, clock=runtime.clock, at=moment
            )
        _ = allocate_ref  # imported for symmetry with other seats; refs allocated in the store
        return mechanism
