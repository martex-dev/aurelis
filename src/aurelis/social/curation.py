"""The seat where an agent chooses whom the company follows (M54).

Until now a handle was followed because a token linked it or a person typed
it. The agents read what those handles posted but had no say in whom to read,
and nobody measured whether a voice was worth reading.

Once a day a market-intelligence agent is shown the record
(:mod:`aurelis.social.voices`): each voice's posts against the move that
followed them and the move that came before, counted by episode, at a bar
divided by how many voices were measured. It may follow voices whose record is
measured and ahead of its peers more often than not, and drop followed voices
whose record is measured and does not lead. Nothing else is offered, and a
reply that names anything else is refused. The measurement is software; the
choice, and the reason, are the agent's.

Every sitting is a ``social.curated`` event, whether the agent followed,
dropped, kept everything, was refused, or was not asked because nothing was
eligible. The record it was shown is stored as an artifact the event cites,
so whether curated voices go on to lead out of sample is a question the
record can answer later.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import sha256_of
from aurelis.core.enums import Actor, EventKind, ModelTier
from aurelis.social.targets import Target, active_targets, drop_target, follow_target
from aurelis.social.voices import (
    HORIZON,
    MIN_EPISODES,
    Voice,
    VoiceBoard,
    measure_voices,
)

__all__ = [
    "CURATE_EVERY",
    "CURATION_FORM",
    "MAX_FOLLOWS",
    "OFFERED",
    "Curation",
    "CurationRefused",
    "curate",
    "curation_due",
    "curator",
    "followed_targets",
]

CURATE_EVERY = dt.timedelta(hours=24)
"""How often the company reviews whom it follows. A record gains at most one
episode per voice per day, so looking more often would show the same record."""

MAX_FOLLOWS = 3
"""Follows per sitting. The X reader reads twelve accounts a wake; a sitting
that followed twenty would push the followed memecoins' own accounts out."""

OFFERED = 15
"""Voices offered to follow per sitting, the strongest records first."""

SYSTEM = (
    "You are a market-intelligence analyst at a quantitative company. The "
    "company reads social media -- X accounts, Telegram channels, Discord "
    "channels -- because attention can form before a price moves. It measures "
    "every voice it has read: whether the instruments a voice posts about beat "
    "their peers over the day after its posts, and whether they had already "
    "beaten them over the day before. You decide whom the company follows from "
    "that record. Follow a voice when its record says its posts come before the "
    "move; drop a followed voice when its record says they do not, or come "
    "after it. A voice that posts after the move is a chaser, however loud. A "
    "record that barely clears a coin toss is weak evidence, and the voices "
    "offered were the best of many, so some look good by luck. Keeping "
    "everything as it is is a legitimate answer. Posts are opinions, not "
    "evidence: judge a voice by its record, never by what it says about itself."
)

CURATION_FORM = (
    "Which voices should the company follow, and which should it drop? Reply in "
    "exactly this form and nothing else:\n"
    f"FOLLOW: <voices from the list you may follow, as written, comma-separated, "
    f"at most {MAX_FOLLOWS}, or none>\n"
    "DROP: <voices from the list you may drop, as written, comma-separated, or none>\n"
    "BECAUSE: <why, in one or two sentences, from the records>\n"
)

_FIELD = re.compile(r"^\s*(FOLLOW|DROP|BECAUSE)\s*:\s*(.*)$", re.I)


class CurationRefused(ValueError):
    """The reply could not be read, or named a voice it was not offered."""


@dataclass(frozen=True, slots=True)
class Curation:
    """What one sitting decided, and on what record."""

    agent_ref: str | None
    asked: bool
    followed: tuple[str, ...]
    dropped: tuple[str, ...]
    because: str
    board: VoiceBoard
    refused: str = ""

    def describe(self) -> str:
        head = (
            f"curation: {len(self.board.voices)} voice(s) read, "
            f"{self.board.measured} measured, {len(self.board.followed())} followed"
        )
        if self.refused:
            return f"{head}; {self.agent_ref} was refused: {self.refused[:120]}"
        if not self.asked:
            if self.board.may_follow() or self.board.may_drop():
                return f"{head}; no market-intelligence agent is active to ask"
            return f"{head}; nothing to decide, nobody asked"
        if not self.followed and not self.dropped:
            return f"{head}; {self.agent_ref} kept every voice as it is"
        parts = []
        if self.followed:
            parts.append(f"followed {', '.join(self.followed)}")
        if self.dropped:
            parts.append(f"dropped {', '.join(self.dropped)}")
        return f"{head}; {self.agent_ref} {' and '.join(parts)}"


def followed_targets(session: Session, *, at: dt.datetime) -> list[Target]:
    """Every handle the next wake reads: explicit follows, and the links of
    the memecoins the dex grants follow now."""
    from aurelis.intel.dex import DexRule, followed_tokens
    from aurelis.service.grants import Grants

    tokens: list[str] = []
    for grant in Grants.active(session):
        if grant.is_dex:
            rule = DexRule.parse(grant.rule, tuple(str(n) for n in grant.instruments))
            tokens += [k for k, _ in followed_tokens(session, rule=rule, at=at) if k not in tokens]
    return active_targets(session, tokens=tuple(tokens))


def curation_due(session: Session, at: dt.datetime) -> bool:
    from aurelis.platform.db.tables import Event

    last = session.execute(
        sa.select(sa.func.max(Event.created_at)).where(Event.kind == EventKind.SOCIAL_CURATED.value)
    ).scalar()
    if last is None:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=dt.UTC)
    return at - last >= CURATE_EVERY


def curator(session: Session) -> Any:
    """The market-intelligence agent who has gone longest without curating."""
    from aurelis.agents.tables import Agent, AgentState
    from aurelis.platform.db.tables import Event

    agents = list(
        session.execute(
            sa.select(Agent)
            .where(
                Agent.department == "market_intelligence",
                Agent.state.in_([AgentState.ACTIVE.value, AgentState.WORKING.value]),
            )
            .order_by(Agent.ref)
        ).scalars()
    )
    if not agents:
        return None
    last: dict[str, int] = {
        str(actor): int(seq)
        for actor, seq in session.execute(
            sa.select(Event.actor, sa.func.max(Event.seq))
            .where(Event.kind == EventKind.SOCIAL_CURATED.value)
            .group_by(Event.actor)
        ).all()
    }
    return min(agents, key=lambda a: (last.get(a.ref) or 0, a.ref))


def _names(raw: str) -> tuple[str, ...]:
    if raw.strip().lower() in ("", "none"):
        return ()
    out: list[str] = []
    for part in raw.split(","):
        name = part.strip().strip("`'\"").lower().replace(":", "/", 1)
        if name and name not in out:
            out.append(name)
    return tuple(out)


def _parse(
    text: str, *, may_follow: set[str], may_drop: set[str]
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    fields: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).upper()
            fields[current] = match.group(2).strip()
        elif current == "BECAUSE" and line.strip():
            fields[current] = f"{fields[current]} {line.strip()}".strip()
    if "FOLLOW" not in fields or "DROP" not in fields:
        raise CurationRefused("the reply needs a FOLLOW line and a DROP line")
    because = fields.get("BECAUSE", "").strip()
    if len(because) <= 10:
        raise CurationRefused("a decision about whom to read needs a reason")
    follows = _names(fields["FOLLOW"])
    drops = _names(fields["DROP"])
    stray = [n for n in follows if n not in may_follow] + [n for n in drops if n not in may_drop]
    if stray:
        raise CurationRefused(f"not offered: {', '.join(stray)}")
    if len(follows) > MAX_FOLLOWS:
        raise CurationRefused(f"{len(follows)} follows; at most {MAX_FOLLOWS} a sitting")
    return follows, drops, because


def _material(board: VoiceBoard, offered: list[Voice], droppable: list[Voice]) -> dict[str, Any]:
    kept = [v for v in board.followed() if v not in droppable]
    return {
        "how_a_voice_is_measured": (
            f"Each post is priced against the other instruments on its desk: the "
            f"instrument's move over the {HORIZON.total_seconds() / 3600:.0f}h after "
            "the post less the median move of its peers over the same hours, and the "
            "same over the hours before. Posts within a day of each other are one "
            f"episode. A record is read from {MIN_EPISODES} episodes."
        ),
        "the_bar": board.describe_bar(),
        "followed_you_may_drop": [f"{v.key}: {v.describe()}" for v in droppable]
        or ["none: every followed voice leads, or is not yet measured"],
        "you_may_follow": [f"{v.key}: {v.describe()}" for v in offered]
        or ["none: no voice the company does not follow has a record ahead of its peers"],
        "followed_and_not_offered": (
            f"{len(kept)} followed voice(s) lead price or are still gathering, and stay"
        ),
    }


def _record(
    runtime: Any,
    session: Session,
    *,
    actor: str,
    board: VoiceBoard,
    asked: bool,
    offered: list[Voice],
    droppable: list[Voice],
    followed: tuple[str, ...] = (),
    dropped: tuple[str, ...] = (),
    because: str = "",
    refused: str = "",
    at: dt.datetime,
) -> None:
    stored = runtime.artifacts.put_json(
        session, board.as_record(), kind="social.voices", produced_by=actor
    )
    runtime.ledger.append(
        session,
        kind=EventKind.SOCIAL_CURATED,
        actor=actor,
        subject="social",
        payload={
            "asked": asked,
            "voices": len(board.voices),
            "measured": board.measured,
            "bar": str(board.bar),
            "offered_follow": [v.key for v in offered],
            "offered_drop": [v.key for v in droppable],
            "followed": list(followed),
            "dropped": list(dropped),
            "because": because[:400],
            "refused": refused[:200],
            "record": stored.digest[:16],
        },
        at=at,
    )


def curate(
    runtime: Any, *, agent_handle: str | None = None, at: dt.datetime | None = None
) -> Curation:
    """Measure every voice, and seat an agent to follow and drop from the record.

    Makes no model call when nothing is eligible either way: idle is free.
    """
    from aurelis.agents.interpret import render_material
    from aurelis.brain.briefing import briefing, system_with_brain
    from aurelis.judgement.seat import identity_of
    from aurelis.platform.llm.routing import model_for
    from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

    moment = at or runtime.clock.now()
    with runtime.database.session() as session:
        targets = followed_targets(session, at=moment)
        board = measure_voices(session, at=moment, targets=targets)
        offered = board.may_follow()[:OFFERED]
        droppable = board.may_drop()
        if agent_handle is None:
            chosen = curator(session)
            agent_handle = chosen.handle if chosen is not None else None
        if agent_handle is None or not (offered or droppable):
            _record(
                runtime,
                session,
                actor=Actor.SYSTEM,
                board=board,
                asked=False,
                offered=offered,
                droppable=droppable,
                at=moment,
            )
            return Curation(None, False, (), (), "", board)
        seated = runtime.roster.by_handle(session, agent_handle)
        task = runtime.queue.enqueue(
            session,
            kind="social.curation",
            assignee=seated.ref,
            payload={"voices": len(board.voices), "measured": board.measured},
            actor=Actor.SYSTEM,
            at=moment,
        )
        claimed = runtime.queue.claim(session, worker=seated.ref, at=moment)
        tier = (
            seated.authority.tier if seated.authority.tier is not ModelTier.NONE else ModelTier.MID
        )
        rendered = f"{render_material(_material(board, offered, droppable))}\n\n{CURATION_FORM}"
        response = runtime.provider.complete(
            session,
            LlmRequest(
                model=ModelRef(
                    provider=runtime.provider.name,
                    model=model_for(runtime.provider.name, tier),
                    tier=tier,
                    max_tokens=400,
                ),
                system=system_with_brain(SYSTEM, identity_of(seated, session), briefing(session)),
                messages=(Message("user", rendered),),
                actor=seated.ref,
                task_ref=claimed.ref if claimed is not None else task.ref,
            ),
        )
        try:
            follows, drops, because = _parse(
                response.text,
                may_follow={v.key for v in offered},
                may_drop={v.key for v in droppable},
            )
        except CurationRefused as error:
            if claimed is not None:
                runtime.queue.fail(session, claimed, error=str(error)[:200], at=moment)
            _record(
                runtime,
                session,
                actor=seated.ref,
                board=board,
                asked=True,
                offered=offered,
                droppable=droppable,
                refused=str(error),
                at=moment,
            )
            return Curation(seated.ref, True, (), (), "", board, refused=str(error))
        for key in follows:
            voice = board.voice(key)
            assert voice is not None
            follow_target(
                session,
                platform=voice.platform,
                handle=voice.handle,
                reason=f"{because} Record when followed: {voice.describe()}",
                decided_by=seated.ref,
                at=moment,
                ledger=runtime.ledger,
            )
        for key in drops:
            voice = board.voice(key)
            assert voice is not None
            drop_target(
                session,
                platform=voice.platform,
                handle=voice.handle,
                reason=f"{because} Record when dropped: {voice.describe()}",
                decided_by=seated.ref,
                at=moment,
                ledger=runtime.ledger,
            )
        _record(
            runtime,
            session,
            actor=seated.ref,
            board=board,
            asked=True,
            offered=offered,
            droppable=droppable,
            followed=follows,
            dropped=drops,
            because=because,
            at=moment,
        )
        if claimed is not None:
            runtime.queue.succeed(
                session,
                claimed,
                result_digest=sha256_of({"follow": list(follows), "drop": list(drops)}),
                at=moment,
            )
        return Curation(seated.ref, True, follows, drops, because, board)
