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
    "DECAY: <how crowded it can get and how fast it dies once others find it>\n"
    "FIRES_ON: trigger | conjunction\n"
    "  (`trigger`: the prediction seals whenever the trigger event fires, on its "
    "own. `conjunction`: it seals only when the second event follows the trigger "
    "inside the window, at the instant of the second event -- the pattern you "
    "were shown, as one occurrence.)\n\n"
    "Or, if you cannot give a causal reason:\n"
    "MECHANISM: nothing\n"
    "BECAUSE: <why not, in one or two sentences>\n\n"
    f"{FIGURE_RULE}"
)

_FIELD = re.compile(
    r"^\s*(MECHANISM|DIRECTION|HORIZON|CONFIDENCE|WHY|OTHER_SIDE|DECAY|FIRES_ON|BECAUSE)"
    r"\s*:\s*(.*)$",
    re.I,
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
    because: str = ""
    """Why the agent declined, when it did. The most useful sentence a decline
    can carry: a record of refusals with no reasons is a record of nothing."""

    fires_on: str = "trigger"
    """``trigger`` or ``conjunction``: whether the mechanism fires on the
    trigger alone or only when the pattern it was shown completes."""

    @property
    def declined(self) -> bool:
        return self.title is None

    @property
    def on_conjunction(self) -> bool:
        return self.fires_on == "conjunction"


def _parse(text: str) -> MechanismProposal:
    fields: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).upper()
            fields[current] = match.group(2).strip()
        elif current in ("WHY", "OTHER_SIDE", "DECAY", "BECAUSE") and line.strip():
            fields[current] = f"{fields[current]} {line.strip()}".strip()

    title = fields.get("MECHANISM", "").strip()
    if title.lower() == "nothing" or not title:
        return MechanismProposal(
            None, "up", 0, Decimal("1"), "", "", "", fields.get("BECAUSE", "").strip()
        )

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
    fires_on = fields.get("FIRES_ON", "trigger").strip().lower() or "trigger"
    if fires_on not in ("trigger", "conjunction"):
        raise MechanismRefused(f"FIRES_ON {fires_on!r} is not trigger or conjunction")
    return MechanismProposal(
        title,
        direction,
        horizon,
        confidence.quantize(Decimal("0.01")),
        why,
        other,
        decay,
        fires_on=fires_on,
    )


_HORIZONS_SHOWN: tuple[int, ...] = (6, 24, 72)


def _material(
    trigger_kind: str,
    second_kind: str,
    pairs: list[CoOccurrence],
    window_hours: int,
    session: Session | None = None,
) -> dict[str, Any]:
    from aurelis.mechanism.mining import effect_of, effect_over

    by_instrument: dict[str, int] = {}
    for pair in pairs:
        by_instrument[pair.entity_key] = by_instrument.get(pair.entity_key, 0) + 1
    evidence: dict[str, str] = {}
    if session is not None:
        seconds: list[Any] = []
        seen: set[str] = set()
        for pair in pairs:
            if pair.second.digest not in seen:
                seen.add(pair.second.digest)
                seconds.append(pair.second)
        for horizon in _HORIZONS_SHOWN:
            effect = effect_of(session, trigger=trigger_kind, horizon_hours=horizon)
            if effect is None:
                continue
            evidence[f"{horizon}h after the trigger"] = (
                f"n {effect.n}, mean {effect.mean_return_after}%, up {effect.up_rate_after}"
            )
            # The same horizon after the conjunction completes: what a
            # mechanism that fires on the pair, at the second event, would be
            # tested on. Shown beside the trigger's so the agent can choose.
            after_pair = effect_over(
                session, seconds, label=f"{trigger_kind} then {second_kind}", horizon_hours=horizon
            )
            if after_pair is not None:
                evidence[f"{horizon}h after the conjunction"] = (
                    f"n {after_pair.n}, mean {after_pair.mean_return_after}%, "
                    f"up {after_pair.up_rate_after}"
                )
            evidence[f"{horizon}h after any bar"] = (
                f"mean {effect.unconditional_mean_return}%, up {effect.unconditional_up_rate}"
            )
    return {
        "pattern": {
            "trigger": trigger_kind,
            "then": second_kind,
            "within hours": window_hours,
            "occurrences": len(pairs),
            "instruments": len(by_instrument),
        },
        "by_instrument": {k: str(v) for k, v in sorted(by_instrument.items())},
        "in_sample_evidence": evidence
        or {"none": "no occurrence of the trigger has a recording that covers its horizon"},
        "note": (
            "The count and the in-sample figures are what the mining found on the "
            "data it was mined from. They are the reason to ask, not evidence the "
            "pattern predicts anything; the out-of-sample predictions a mechanism "
            "seals as the trigger fires again are the test. A causal reason is "
            "what makes a mechanism, and only one that would also hold on data "
            "the mining never saw is worth stating."
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
    artifacts: Any = None,
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
    material = _material(trigger_kind, second_kind, pairs, window_hours, session=session)
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair.entity_key] = counts.get(pair.entity_key, 0) + 1
    found_on = max(sorted(counts), key=lambda k: counts[k])
    found_pair = next(p for p in pairs if p.entity_key == found_on)

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
                payload={
                    "trigger": trigger_kind,
                    "then": second_kind,
                    "because": proposal.because[:400],
                },
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
    evidence_digest = ""
    if artifacts is not None:
        evidence_digest = artifacts.put_json(
            session,
            {"pattern": material["pattern"], "evidence": material["in_sample_evidence"]},
            kind="mechanism.evidence",
            produced_by=agent_ref,
            actor=agent_ref,
        ).digest
    # The training occurrence is the event the mechanism fires on: the trigger
    # of the strongest instrument's first pair, or -- on a conjunction -- the
    # second event that completed it.
    found_event = found_pair.second.digest if proposal.on_conjunction else found_pair.first.digest
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
        evidence_digest=evidence_digest,
        then_kind=second_kind if proposal.on_conjunction else None,
        within_hours=window_hours if proposal.on_conjunction else None,
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
            artifacts=runtime.artifacts,
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
