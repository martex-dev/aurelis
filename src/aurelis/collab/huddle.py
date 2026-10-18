"""Huddles: two agents who disagree, in one room (M64).

When two agents hold opposite open views on the same market (one sealed
*up*, the other *down*), the company has a disagreement on the record, and
until now nobody talked about it. A huddle is a short real meeting about it:

1. **Brief.** Both sealed views, word for word, are the evidence pack.
2. **Opening.** Each makes its case, having read the other's view.
3. **Rebuttal.** Each answers the other and states a revised probability
   that the market is up at its own view's horizon.
4. **Position.** A moderator who holds neither view (the Critic, or the Lead
   Researcher when the Critic is one of the two) writes the company's position
   and one line for the shared brain.

Every turn is a ``meeting_turns`` row, the position is a ``decisions`` row,
and the line is a brain note. The meeting is ``productive`` because it
changes those two things.

**Whether talking helps is measured, not assumed.** The sealed views stand:
nothing said in a huddle changes them. The revised probabilities are kept in
the decision. When the views resolve, :func:`huddle_record` scores the
probability each agent held before the huddle (its sealed view) and the one
it gave after, against what happened. If the company's agents are better
calibrated after talking, that is evidence for meetings. If they are worse,
it is evidence against, and the company should hold fewer.

Cost: five model calls per huddle. At most :data:`PER_WAKE` per wake and
:data:`PER_DAY` per day, and never two on the same market in a day.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.enums import EventKind, ModelTier
from aurelis.core.ids import RefKind, uuid7

__all__ = [
    "HUDDLE",
    "PER_DAY",
    "PER_WAKE",
    "Disagreement",
    "HuddleRecord",
    "disagreements",
    "hold_huddle",
    "hold_huddles",
    "huddle_record",
]

HUDDLE = "huddle"
PER_WAKE = 2
PER_DAY = 6
CALLS = 5
WINDOW = dt.timedelta(hours=24)

HUDDLE_SYSTEM = """\
You work at Aurelis, an autonomous quantitative research company made of AI agents. \
You are in a huddle: a short meeting called because two agents hold opposite open \
views on the same market. Argue from evidence, in plain words, briefly (under about \
120 words). Change your mind if the other side is right; say so if they are not. \
Only quote numbers that appear in what you are shown."""

_PROB = re.compile(r"PROBABILITY_UP\s*:\s*([0-9]*\.?[0-9]+)\s*(%?)", re.IGNORECASE)
_POSITION = re.compile(r"POSITION\s*:\s*(up|down|none)", re.IGNORECASE)
_NOTE = re.compile(r"NOTE\s*:\s*(.+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Disagreement:
    instrument: str
    up: Any
    """The open view that says up (a ``Thesis``)."""
    down: Any


def _utc(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def disagreements(session: Session, now: dt.datetime) -> list[Disagreement]:
    """Open views that contradict each other, on markets with no huddle today."""
    from aurelis.judgement.tables import Thesis
    from aurelis.meetings.tables import Meeting

    now = _utc(now)
    open_views = list(
        session.execute(
            sa.select(Thesis)
            .where(
                Thesis.scored_at.is_(None),
                Thesis.mechanism_ref.is_(None),
                Thesis.direction.in_(("up", "down")),
            )
            .order_by(Thesis.sealed_at.desc())
        ).scalars()
    )
    recent = set(
        session.execute(
            sa.select(Meeting.subject_ref).where(
                Meeting.type == HUDDLE, Meeting.convened_at >= now - WINDOW
            )
        ).scalars()
    )
    found: list[Disagreement] = []
    seen: set[str] = set()
    for view in open_views:
        if view.instrument in seen or view.instrument in recent:
            continue
        opposite = next(
            (
                other
                for other in open_views
                if other.instrument == view.instrument
                and other.direction != view.direction
                and other.agent_ref != view.agent_ref
            ),
            None,
        )
        if opposite is None:
            continue
        up, down = (view, opposite) if view.direction == "up" else (opposite, view)
        found.append(Disagreement(view.instrument, up, down))
        seen.add(view.instrument)
    return found


def _speaks(thesis: Any) -> str:
    return (
        f"{thesis.agent_ref} sealed: {thesis.instrument} {thesis.direction} over "
        f"{thesis.horizon_hours}h at confidence {thesis.confidence}. Thesis: {thesis.thesis} "
        f"Wrong if: {thesis.wrong_if}"
    )


def _probability(text: str) -> Decimal | None:
    match = _PROB.search(text)
    if match is None:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    if match.group(2) or value > 1:
        value = value / 100
    return value if Decimal(0) <= value <= Decimal(1) else None


def _call(runtime: Any, session: Session, seated: Any, identity: str, prompt: str) -> str:
    from aurelis.brain.briefing import briefing, system_with_brain
    from aurelis.platform.llm.routing import model_for
    from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

    tier = seated.authority.tier if seated.authority.tier is not ModelTier.NONE else ModelTier.MID
    system = system_with_brain(HUDDLE_SYSTEM, identity, briefing(session))
    response = runtime.provider.complete(
        session,
        LlmRequest(
            model=ModelRef(
                provider=runtime.provider.name,
                model=model_for(runtime.provider.name, tier),
                tier=tier,
                max_tokens=450,
            ),
            system=system,
            messages=(Message("user", prompt),),
            actor=seated.ref,
        ),
    )
    return str(response.text).strip()


def _turn(
    session: Session,
    meeting_ref: str,
    seq: int,
    phase: str,
    speaker: str,
    body: str,
    at: dt.datetime,
    *,
    stance: str = "uncertain",
    addressed_to: tuple[str, ...] = (),
) -> None:
    from aurelis.meetings.tables import MeetingTurn

    session.add(
        MeetingTurn(
            turn_id=uuid7(),
            meeting_ref=meeting_ref,
            seq=seq,
            round=1 if phase == "exchange" else 0,
            phase=phase,
            speaker=speaker,
            addressed_to=list(addressed_to),
            kind="statement",
            body=body[:4000],
            claims=[],
            evidence_refs=[],
            stance=stance,
            created_at=at,
        )
    )
    session.flush()


def _moderator(runtime: Any, session: Session, a: str, b: str) -> Any:
    for handle in ("CRITIC", "LEAD-R", "VALID", "STRAT"):
        try:
            agent = runtime.roster.by_handle(session, handle)
        except KeyError:
            continue
        if agent.ref not in (a, b):
            return agent
    return None


def hold_huddle(runtime: Any, disagreement: Disagreement, *, at: dt.datetime) -> str | None:
    """Hold one huddle on one disagreement; the meeting ref, or ``None``."""
    from aurelis.agents.interpret import allowed_figures
    from aurelis.agents.tables import Agent
    from aurelis.brain.notes import leave_note
    from aurelis.judgement.seat import identity_of
    from aurelis.meetings.tables import Decision, Meeting, MeetingParticipant
    from aurelis.platform.db.refs import allocate_ref

    up, down = disagreement.up, disagreement.down
    with runtime.database.session() as session:
        handles = dict(
            session.execute(
                sa.select(Agent.ref, Agent.handle).where(
                    Agent.ref.in_((up.agent_ref, down.agent_ref))
                )
            ).all()
        )
        if len(handles) < 2:
            return None
        bull = runtime.roster.by_handle(session, handles[up.agent_ref])
        bear = runtime.roster.by_handle(session, handles[down.agent_ref])
        moderator = _moderator(runtime, session, bull.ref, bear.ref)
        if moderator is None:
            return None
        pack = {"instrument": disagreement.instrument, "up": _speaks(up), "down": _speaks(down)}
        ref = allocate_ref(session, RefKind.MEETING)
        session.add(
            Meeting(
                meeting_id=uuid7(),
                ref=ref,
                type=HUDDLE,
                subject=f"{bull.handle} says up, {bear.handle} says down on "
                f"{disagreement.instrument}",
                trigger=f"opposite open views {up.ref} and {down.ref}",
                subject_ref=disagreement.instrument,
                department="strategy_laboratory",
                desk=up.desk,
                chair=moderator.ref,
                agenda=[
                    "Each side's case",
                    "Each answers the other, with a revised probability",
                    "The company's position",
                ],
                evidence_pack=pack,
                budget_tokens=6000,
                budget_rounds=1,
                max_turn_tokens=450,
                status="in_session",
                convened_at=at,
            )
        )
        for agent_ref, attendance in (
            (moderator.ref, "chair"),
            (bull.ref, "required"),
            (bear.ref, "required"),
        ):
            session.add(
                MeetingParticipant(
                    meeting_ref=ref,
                    agent_ref=agent_ref,
                    attendance=attendance,
                    charters_at_the_time=list(runtime.roster.coverage_of(session, agent_ref)),
                )
            )
        session.flush()
        runtime.ledger.append(
            session,
            kind=EventKind.MEETING_CONVENED,
            actor=moderator.ref,
            subject=ref,
            payload={
                "type": HUDDLE,
                "subject": f"{disagreement.instrument}: {bull.handle} up, {bear.handle} down",
                "participants": [bull.ref, bear.ref],
                "views": [up.ref, down.ref],
            },
            at=at,
        )
        ids = {s.ref: identity_of(s, session) for s in (bull, bear, moderator)}

    brief = f"The disagreement, on {disagreement.instrument}:\n- {pack['up']}\n- {pack['down']}"
    said: dict[str, str] = {}
    revised: dict[str, Decimal | None] = {}
    seq = 0
    with runtime.database.session() as session:
        for speaker, own in ((bull, up), (bear, down)):
            said[speaker.ref] = _call(
                runtime,
                session,
                speaker,
                ids[speaker.ref],
                f"{brief}\n\nYou are {speaker.handle}; your sealed view is the "
                f"{own.direction} one. Make your case to the room.",
            )
            seq += 1
            _turn(
                session,
                ref,
                seq,
                "opening",
                speaker.ref,
                said[speaker.ref],
                at,
                stance="support" if own.direction == "up" else "oppose",
            )
        for speaker, own, other in ((bull, up, bear), (bear, down, bull)):
            reply = _call(
                runtime,
                session,
                speaker,
                ids[speaker.ref],
                f"{brief}\n\n{other.handle} said: {said[other.ref]}\n\nYou are "
                f"{speaker.handle}. Answer {other.handle} in a few sentences, then on its own "
                f"line state the probability you now give that {disagreement.instrument} "
                f"closes up at the {own.horizon_hours}h horizon of your view:\n"
                "PROBABILITY_UP: <a number from 0 to 1>",
            )
            revised[speaker.ref] = _probability(reply)
            seq += 1
            _turn(session, ref, seq, "exchange", speaker.ref, reply, at, addressed_to=(other.ref,))
            said[f"{speaker.ref}:rebuttal"] = reply
        transcript = "\n".join(
            f"{name}: {said[key]}"
            for name, key in (
                (bull.handle, bull.ref),
                (bear.handle, bear.ref),
                (bull.handle, f"{bull.ref}:rebuttal"),
                (bear.handle, f"{bear.ref}:rebuttal"),
            )
        )
        closing = _call(
            runtime,
            session,
            moderator,
            ids[moderator.ref],
            f"{brief}\n\nThe huddle:\n{transcript}\n\nYou are {moderator.handle}, moderating; "
            "you hold neither view. Weigh the arguments, not the confidence. Reply with:\n"
            "POSITION: up | down | none\n"
            "WHY: <two or three sentences>\n"
            "NOTE: <one line for the shared brain, for every agent>",
        )
        seq += 1
        _turn(session, ref, seq, "synthesis", moderator.ref, closing, at)
        position = (
            _POSITION.search(closing).group(1).lower()  # type: ignore[union-attr]
            if _POSITION.search(closing)
            else "none"
        )
        decision_ref = allocate_ref(session, RefKind.DECISION)
        views = (
            (bull, up),
            (bear, down),
        )
        session.add(
            Decision(
                decision_id=uuid7(),
                ref=decision_ref,
                meeting_ref=ref,
                subject=f"the company's position on {disagreement.instrument}"[:256],
                outcome=position,
                rationale=closing[:2000],
                supporting=[
                    {
                        "agent": agent.ref,
                        "thesis": thesis.ref,
                        "before_up": str(thesis.probability_up),
                        "after_up": None
                        if revised.get(agent.ref) is None
                        else str(revised[agent.ref]),
                    }
                    for agent, thesis in views
                ],
                dissent=[],
                evidence_refs=[up.ref, down.ref],
                decided_by=moderator.ref,
                decided_at=at,
            )
        )
        note_match = _NOTE.search(closing)
        note = leave_note(
            session,
            author=moderator.ref,
            text=note_match.group(1).strip() if note_match else "",
            topics=(disagreement.instrument,),
            source_ref=f"huddle {ref}",
            permitted=allowed_figures({"pack": pack, "talk": transcript}),
            ledger=runtime.ledger,
            at=at,
        )
        meeting = session.execute(sa.select(Meeting).where(Meeting.ref == ref)).scalar_one()
        meeting.status = "closed"
        meeting.closed_at = at
        meeting.productive = True
        meeting.state_changes = 1 + (note is not None)
        meeting.rounds_used = 1
        session.flush()
        runtime.ledger.append(
            session,
            kind=EventKind.DECISION_RECORDED,
            actor=moderator.ref,
            subject=decision_ref,
            payload={"meeting": ref, "position": position, "instrument": disagreement.instrument},
            at=at,
        )
        runtime.ledger.append(
            session,
            kind=EventKind.MEETING_CLOSED,
            actor=moderator.ref,
            subject=ref,
            payload={
                "type": HUDDLE,
                "position": position,
                "revised": {k: (None if v is None else str(v)) for k, v in revised.items()},
                "note": note.ref if note is not None else None,
            },
            at=at,
        )
    return ref


def hold_huddles(runtime: Any, *, at: dt.datetime, calls_left: int) -> list[str]:
    """Hold the huddles that are due, within the wake's and the day's caps."""
    from aurelis.meetings.tables import Meeting

    moment = _utc(at)
    with runtime.database.session() as session:
        today = int(
            session.execute(
                sa.select(sa.func.count()).where(
                    Meeting.type == HUDDLE, Meeting.convened_at >= moment - WINDOW
                )
            ).scalar_one()
        )
        due = disagreements(session, moment)
    held: list[str] = []
    for item in due:
        if len(held) >= PER_WAKE or today + len(held) >= PER_DAY:
            break
        if calls_left - CALLS * len(held) < CALLS:
            break
        ref = hold_huddle(runtime, item, at=moment)
        if ref is not None:
            held.append(ref)
    return held


@dataclass(frozen=True, slots=True)
class HuddleRecord:
    held: int
    resolved: int
    """Agent views whose huddle gave a revised probability and that have scored."""
    brier_before: Decimal | None
    brier_after: Decimal | None

    def verdict(self) -> str:
        if self.brier_before is None or self.brier_after is None or self.resolved < 10:
            return "too few resolved to say whether talking helps"
        if self.brier_after < self.brier_before:
            return "agents were better calibrated after talking"
        if self.brier_after > self.brier_before:
            return "agents were worse calibrated after talking"
        return "talking made no difference"


def huddle_record(session: Session) -> HuddleRecord:
    """Before against after: does a huddle make its agents better forecasters?"""
    from aurelis.judgement.tables import Thesis
    from aurelis.meetings.tables import Decision, Meeting

    held = int(
        session.execute(
            sa.select(sa.func.count()).where(Meeting.type == HUDDLE, Meeting.status == "closed")
        ).scalar_one()
    )
    rows = session.execute(
        sa.select(Decision.supporting)
        .join(Meeting, Meeting.ref == Decision.meeting_ref)
        .where(Meeting.type == HUDDLE)
    ).scalars()
    before: list[Decimal] = []
    after: list[Decimal] = []
    for supporting in rows:
        for entry in supporting or []:
            if entry.get("after_up") is None:
                continue
            thesis = session.execute(
                sa.select(Thesis).where(Thesis.ref == entry.get("thesis"))
            ).scalar_one_or_none()
            if thesis is None or thesis.outcome is None:
                continue
            truth = Decimal(1 if thesis.outcome else 0)
            before.append((Decimal(entry["before_up"]) - truth) ** 2)
            after.append((Decimal(entry["after_up"]) - truth) ** 2)
    q = Decimal("0.0001")
    return HuddleRecord(
        held=held,
        resolved=len(after),
        brier_before=(sum(before, Decimal(0)) / len(before)).quantize(q) if before else None,
        brier_after=(sum(after, Decimal(0)) / len(after)).quantize(q) if after else None,
    )
