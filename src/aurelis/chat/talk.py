"""Talking to an agent (M62).

The operator clicks an agent in the Office and talks to it. The agent answers
from the same seat it works from, as the same person:

- its identity, charters and current method (what it is told at every seat);
- the shared brain every agent reads;
- its own record: how its sealed views scored and its latest notes;
- the conversation so far.

**What a conversation can and cannot do.** It can explain, argue, disagree
and suggest. It cannot act. No tool is offered, the seat is the same sandbox
every other seat runs in (ADR-0024), and nothing an agent says here becomes a
view, an order, a grant or a change to the company. An instruction the
operator gives is recorded as said, and the Company Manager is where
instructions will be turned into work (M63).

**Figures.** The figure guard that refuses a sealed view citing a number the
agent was not shown would make a conversation useless if it refused answers.
So here it flags instead: each answer carries the list of numerals it used that
were not in its material, and the Office shows them beside the answer.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.chat.tables import ChatTurn
from aurelis.core.enums import Actor, EventKind, ModelTier
from aurelis.core.ids import RefKind, uuid7
from aurelis.platform.db.refs import allocate_ref

__all__ = ["CHAT_SYSTEM", "Exchange", "ask", "thread"]

HISTORY = 12
"""Turns of the conversation so far an agent is shown when it answers."""

CHAT_SYSTEM = """\
You work at Aurelis, an autonomous quantitative research company made of AI agents. \
You are talking, in the company's Office, with the operator: the person who owns \
the company and decides when, if ever, it trades real money.

How to talk:
- Answer in plain, friendly words. The operator is not a quant; explain like a good \
teacher, short sentences, examples where they help.
- Be honest. Say what your record says, including when it says you are no better \
than a coin toss. Never call anything profitable that the record does not show to be.
- Disagree when you disagree, and say why. The company exists to find out what is \
true, not to please anyone.
- Only quote numbers that are in what you are shown below. If you do not know a \
number, say so; do not estimate one and present it as fact.
- You cannot act from this conversation: you cannot trade, seal a view, change a \
setting or spend money. If the operator asks you to do something, say what you \
would do and why; the request is recorded, and the Company Manager turns \
instructions into work.
- Keep answers under about 250 words unless the operator asks for more."""


@dataclass(frozen=True, slots=True)
class Exchange:
    question: ChatTurn
    answer: ChatTurn | None
    error: str = ""


def thread(session: Session, agent_ref: str, *, limit: int = 60) -> list[ChatTurn]:
    """The conversation with one agent, oldest first."""
    rows = list(
        session.execute(
            sa.select(ChatTurn)
            .where(ChatTurn.agent_ref == agent_ref)
            .order_by(ChatTurn.said_at.desc(), ChatTurn.ref.desc())
            .limit(limit)
        ).scalars()
    )
    return list(reversed(rows))


def _staffed(runtime: Any, session: Session, agent_ref: str) -> Any:
    from aurelis.agents.tables import Agent

    handle = session.execute(
        sa.select(Agent.handle).where(Agent.ref == agent_ref, Agent.retired_at.is_(None))
    ).scalar_one_or_none()
    if handle is None:
        raise KeyError(f"no agent {agent_ref!r} works here")
    return runtime.roster.by_handle(session, handle)


def _record(session: Session, agent_ref: str) -> str:
    """The agent's own record, as lines it may quote."""
    from aurelis.brain.tables import BrainNote
    from aurelis.judgement.seat import _own_record

    record = _own_record(session, agent_ref)
    lines = [f"- {key.replace('_', ' ')}: {value}" for key, value in record.items()]
    notes = session.execute(
        sa.select(BrainNote.text)
        .where(BrainNote.author == agent_ref)
        .order_by(BrainNote.written_at.desc())
        .limit(4)
    ).scalars()
    lines += [f"- a note you left: {text[:300]}" for text in notes]
    return "\n".join(lines) or "- nothing yet"


def _conversation(turns: list[ChatTurn], handle: str) -> str:
    return "\n".join(
        f"{'Operator' if t.speaker == 'operator' else handle}: {t.text}" for t in turns
    )


def _turn(
    session: Session,
    *,
    agent_ref: str,
    speaker: str,
    text: str,
    at: dt.datetime,
    in_reply_to: str | None = None,
    model: str | None = None,
    unsourced: list[str] | None = None,
) -> ChatTurn:
    turn = ChatTurn(
        turn_id=uuid7(),
        ref=allocate_ref(session, RefKind.CHAT),
        agent_ref=agent_ref,
        speaker=speaker,
        text=text,
        in_reply_to=in_reply_to,
        model=model,
        unsourced=list(unsourced or []),
        said_at=at,
    )
    session.add(turn)
    session.flush()
    return turn


def ask(runtime: Any, agent_ref: str, text: str, *, at: dt.datetime | None = None) -> Exchange:
    """The operator says ``text`` to an agent; the agent answers.

    The operator's line is committed before the model is asked, so what was
    said is on the record even when the agent cannot answer (the company is
    asleep, or the provider fails). The model is asked outside any write, so a
    slow answer does not hold the database against the hourly service.
    """
    from aurelis.agents.interpret import allowed_figures, unsourced_numerals
    from aurelis.brain.briefing import briefing, system_with_brain
    from aurelis.judgement.seat import identity_of
    from aurelis.platform.llm.routing import model_for
    from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

    text = text.strip()
    if not text:
        raise ValueError("say something")
    moment = at or runtime.clock.now()

    with runtime.database.session() as session:
        seated = _staffed(runtime, session, agent_ref)
        earlier = thread(session, agent_ref, limit=HISTORY)
        question = _turn(session, agent_ref=agent_ref, speaker="operator", text=text, at=moment)
        runtime.ledger.append(
            session,
            kind=EventKind.CHAT_ASKED,
            actor=Actor.OPERATOR,
            subject=agent_ref,
            payload={"turn": question.ref, "agent": agent_ref, "text": text[:300]},
            at=moment,
        )
        session.expunge(question)

    tier = seated.authority.tier if seated.authority.tier is not ModelTier.NONE else ModelTier.MID
    try:
        with runtime.database.session() as session:
            identity = identity_of(seated, session)
            system = system_with_brain(CHAT_SYSTEM, identity, briefing(session))
            record = _record(session, agent_ref)
            so_far = _conversation(earlier, seated.handle)
            prompt = (
                f"Your own record:\n{record}\n\n"
                + (f"The conversation so far:\n{so_far}\n\n" if so_far else "")
                + f"The operator says: {text}\n\nAnswer the operator as {seated.handle}."
            )
            model_id = model_for(runtime.provider.name, tier)
            response = runtime.provider.complete(
                session,
                LlmRequest(
                    model=ModelRef(
                        provider=runtime.provider.name, model=model_id, tier=tier, max_tokens=900
                    ),
                    system=system,
                    messages=(Message("user", prompt),),
                    actor=agent_ref,
                    task_ref=None,
                ),
            )
            reply = response.text.strip() or "(no answer)"
            flagged = unsourced_numerals(
                reply, allowed_figures({"system": system, "prompt": prompt})
            )
            answer = _turn(
                session,
                agent_ref=agent_ref,
                speaker="agent",
                text=reply,
                at=runtime.clock.now(),
                in_reply_to=question.ref,
                model=model_id,
                unsourced=flagged,
            )
            runtime.ledger.append(
                session,
                kind=EventKind.CHAT_ANSWERED,
                actor=agent_ref,
                subject=agent_ref,
                payload={
                    "turn": answer.ref,
                    "in_reply_to": question.ref,
                    "text": reply[:300],
                    "unsourced": len(flagged),
                },
                at=answer.said_at,
            )
            session.expunge(answer)
    except Exception as error:  # noqa: BLE001 - the question stands; say why there is no answer
        return Exchange(question, None, f"{type(error).__name__}: {error}")
    return Exchange(question, answer)
