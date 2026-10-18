"""Asking a colleague (M64).

The operator wanted agents to work together: "the traders say that they need
all the current information about forex to the researchers and news
analyzers and trackers, and they immediately give them the information".
Before M64 the live company's agents had sent each other no messages. Each
worked alone from the shared brain.

This module is the one way an agent asks another for help. The question
travels as a real message (``comms``, QUESTION) and so does the answer
(ANSWER). The colleague answers from its own seat, as itself: its charters
and method, the shared brain, its own record, and the brain's notes on what
it is being asked about. Two callers use it:

- an agent stating a view, who may ask one colleague one question before
  deciding (``judgement/seat.py``);
- the Company Manager, asking on the operator's behalf (``manager/portal.py``).

An answer is an opinion, like a note in the brain. The asker is told so, and
the figure guard does not accept a number that appears only in an answer.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.enums import EventKind, ModelTier

__all__ = [
    "COLLEAGUE_SYSTEM",
    "Consultant",
    "ask_hint",
    "consult",
    "colleagues",
    "parse_ask",
]

COLLEAGUE_SYSTEM = """\
You work at Aurelis, an autonomous quantitative research company made of AI agents. \
A colleague is asking you for help with their work. Answer honestly and briefly \
(under about 150 words), in plain words, from your own specialism, work and record. \
Only quote numbers that appear in what you are shown. If you do not know, say so: a \
colleague is better served by "I have nothing on that" than by a guess."""

_ASK = re.compile(r"^\s*ASK\s*:\s*([A-Za-z0-9_-]+)\s*:\s*(.+)$", re.IGNORECASE)


def colleagues(session: Session, *, besides: str) -> list[tuple[str, str]]:
    """``(handle, department)`` for everybody on the payroll but ``besides``."""
    from aurelis.agents.tables import Agent

    rows = session.execute(
        sa.select(Agent.handle, Agent.department)
        .where(Agent.retired_at.is_(None), Agent.ref != besides)
        .order_by(Agent.handle)
    ).all()
    return [(str(h), str(d)) for h, d in rows]


def ask_hint(people: list[tuple[str, str]]) -> str:
    """The line a seat adds so its agent knows it may ask, and whom."""
    roster = ", ".join(f"{h} ({d.replace('_', ' ')})" for h, d in people)
    return (
        "You may ask ONE colleague ONE question before you answer, if what they know "
        "would change your view (news, flows, social, risk, what a mechanism has done). "
        "To ask, reply with only this line, and nothing else:\n"
        "ASK: <HANDLE>: <your question>\n"
        f"Colleagues: {roster}."
    )


def parse_ask(text: str, handles: set[str]) -> tuple[str, str] | None:
    """The colleague and question, if the reply is a request for help and not an answer."""
    if re.search(r"^\s*DIRECTION\s*:", text, re.IGNORECASE | re.MULTILINE):
        return None
    for line in text.splitlines():
        match = _ASK.match(line)
        if match:
            handle = match.group(1).upper()
            question = match.group(2).strip()
            if handle in handles and question:
                return handle, question[:500]
    return None


def _post(
    runtime: Any, session: Session, sender: str, to: str, kind: Any, body: str, at: dt.datetime
) -> str | None:
    """A real message, if the sender's charter may write one. Returns its ref."""
    try:
        with session.begin_nested():
            message = runtime.comms.post(
                session,
                from_agent=sender,
                kind=kind,
                subject=body[:120],
                body=body,
                to_agents=(to,),
                requires_response=kind.value == "question",
                at=at,
            )
        return str(message.ref)
    except Exception:  # noqa: BLE001 - a charter without the scope still asked; the event says so
        return None


def _session(runtime: Any, given: Session | None) -> Any:
    """The caller's session if it has one, else a new one of our own."""
    from contextlib import nullcontext

    return nullcontext(given) if given is not None else runtime.database.session()


def consult(
    runtime: Any,
    *,
    asker: str,
    handle: str,
    question: str,
    topics: tuple[str, ...] = (),
    preface: str = "",
    at: dt.datetime | None = None,
    session: Session | None = None,
) -> tuple[str, str]:
    """``asker`` asks the colleague ``handle``; returns ``(colleague_ref, answer)``.

    ``session`` is the caller's, when the caller is a seat already inside a
    write: SQLite has one writer, and a second session would wait on the first
    until it timed out. Without one, the question is written and committed
    before the model is asked, and the model is asked outside any write.

    The question and the answer are messages, and the exchange is an
    ``agent.consulted`` event, so the station shows who helped whom.
    """
    from aurelis.brain.briefing import briefing, system_with_brain, topic_block
    from aurelis.chat.talk import _record
    from aurelis.comms.tables import MessageKind
    from aurelis.judgement.seat import identity_of
    from aurelis.platform.llm.routing import model_for
    from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

    moment = at or runtime.clock.now()
    given = session
    with _session(runtime, given) as session:
        colleague = runtime.roster.by_handle(session, handle)
        asked_ref = _post(
            runtime, session, asker, colleague.ref, MessageKind.QUESTION, question, moment
        )
        identity = identity_of(colleague, session)
        system = system_with_brain(COLLEAGUE_SYSTEM, identity, briefing(session, topics))
        on_it = topic_block(session, list(topics)) if topics else ""
        prompt = (
            f"Your own record:\n{_record(session, colleague.ref)}\n\n"
            + (f"Notes in the shared brain on this (opinions):\n{on_it}\n\n" if on_it else "")
            + (f"{preface}\n" if preface else "")
            + f"A colleague asks you: {question}\n\nAnswer as {colleague.handle}."
        )
    tier = (
        colleague.authority.tier
        if colleague.authority.tier is not ModelTier.NONE
        else ModelTier.MID
    )
    with _session(runtime, given) as session:
        model_id = model_for(runtime.provider.name, tier)
        response = runtime.provider.complete(
            session,
            LlmRequest(
                model=ModelRef(
                    provider=runtime.provider.name, model=model_id, tier=tier, max_tokens=500
                ),
                system=system,
                messages=(Message("user", prompt),),
                actor=colleague.ref,
            ),
        )
        answer = str(response.text).strip() or "(no answer)"
        answered_ref = _post(
            runtime, session, colleague.ref, asker, MessageKind.ANSWER, answer, moment
        )
        runtime.ledger.append(
            session,
            kind=EventKind.AGENT_CONSULTED,
            actor=asker,
            subject=colleague.ref,
            payload={
                "question": question[:300],
                "answer": answer[:300],
                "topics": list(topics)[:5],
                "messages": [r for r in (asked_ref, answered_ref) if r],
            },
            at=moment,
        )
    return colleague.ref, answer


@dataclass(frozen=True, slots=True)
class Consultant:
    """What a seat holds so its agent may ask for help: who, and how."""

    runtime: Any
    asker: str
    people: tuple[tuple[str, str], ...]

    @property
    def handles(self) -> set[str]:
        return {h for h, _ in self.people}

    def hint(self) -> str:
        return ask_hint(list(self.people))

    def __call__(
        self,
        handle: str,
        question: str,
        *,
        topics: tuple[str, ...],
        at: dt.datetime,
        session: Session | None = None,
    ) -> str:
        return consult(
            self.runtime,
            asker=self.asker,
            handle=handle,
            question=question,
            topics=topics,
            at=at,
            session=session,
        )[1]
