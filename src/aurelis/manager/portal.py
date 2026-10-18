"""The Company Manager: the operator's one portal into the company (M63).

The operator talks to one agent, the Company Manager (the CEO charter), in
the Control Room. The Manager answers from the company's whole situation,
and can do three things about what the operator says:

1. **Write a directive.** A standing instruction every agent reads at every
   seat, in the shared brain (``directives.py``). This is how "focus on
   Solana meme coins this week" becomes different work.
2. **Withdraw a directive** the operator no longer wants.
3. **Ask colleagues.** Up to three agents, each by name, each answering from
   its own seat. The question and the answer travel as real messages
   between agents (the first the live company has sent each other). The
   Manager then reports back to the operator with what they said.

It cannot do anything else. It cannot trade, grant data, change a budget,
lift a Risk limit or turn on real money, and its prompt says so. Each of those
belongs to a person or to Risk, and none has a path from here.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.chat.talk import Exchange, _conversation, _staffed, _turn, thread
from aurelis.core.enums import Actor, EventKind, ModelTier

__all__ = ["MANAGER_HANDLE", "MANAGER_SYSTEM", "Plan", "manage", "manager_ref", "parse"]

MANAGER_HANDLE = "CEO"
MAX_ASKS = 3
HISTORY = 12

MANAGER_SYSTEM = """\
You are the Company Manager of Aurelis, an autonomous quantitative research company \
made of AI agents. You work in the Control Room. The operator (the person who owns the \
company) talks to you, and only you, about everything: you are their one portal.

Talk like a friendly, honest teacher: plain words, short sentences, no jargon \
without explaining it. Never call anything profitable that the record does not show \
to be. When the record says the company has not found an edge, say so kindly and \
clearly.

You can do three things besides talking. Each is one line in your answer, after \
your reply:
- DIRECTIVE: <one clear instruction to the company> | TO: all
  (or | TO: HANDLE, HANDLE to address specific agents). Every agent reads active \
directives at every seat, so this is how an instruction becomes work. Write one when \
the operator asks the company to do, focus on, avoid or try something. Make it \
concrete and something the company can actually do with the data it has.
- REVOKE: DIR-0000  to withdraw a directive the operator no longer wants.
- ASK: HANDLE: <question>  to ask a colleague (up to three). They answer from their \
own seat and you will be shown what they said before you report back. Ask when the \
operator wants to know what a particular agent thinks or is doing.

What you cannot do, and must say plainly when asked: trade, place or size orders, \
grant the company new data (that is the operator's own command), change budgets, \
override Risk, or turn on real money. Real money needs the company's own mandate to \
say READY and then the operator to act. If the operator asks for something the \
company has no data for (for example a market with no feed), say what is missing \
and what the operator would need to do.

Format: start with "REPLY:" and your answer to the operator, then any DIRECTIVE, \
REVOKE or ASK lines, each on its own line. Only quote numbers that appear in what \
you are shown."""

@dataclass(frozen=True, slots=True)
class Plan:
    reply: str
    directives: tuple[tuple[str, tuple[str, ...]], ...] = ()
    revokes: tuple[str, ...] = ()
    asks: tuple[tuple[str, str], ...] = ()


@dataclass(slots=True)
class Done:
    """What the Manager did about one thing the operator said."""

    issued: list[tuple[str, str, str]] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)
    asked: list[tuple[str, str, str]] = field(default_factory=list)
    """(handle, question, answer)"""

    def lines(self) -> list[str]:
        out = [f"• Directive {ref} for {who}: {text}" for ref, who, text in self.issued]
        out += [f"• Withdrew {ref}" for ref in self.revoked]
        out += [f"• Asked {handle}: {question}" for handle, question, _ in self.asked]
        return out


_KEY = re.compile(r"^\s*(REPLY|DIRECTIVE|REVOKE|ASK)\s*:\s*(.*)$", re.IGNORECASE)


def parse(text: str, handles: set[str]) -> Plan:
    """Read the Manager's answer into a reply and the actions it asked for.

    Unknown handles are dropped rather than guessed at. A directive with no
    known audience goes to everyone. Anything before the first keyword is
    treated as the reply.
    """
    reply: list[str] = []
    directives: list[tuple[str, tuple[str, ...]]] = []
    revokes: list[str] = []
    asks: list[tuple[str, str]] = []
    current = "REPLY"
    for line in text.splitlines():
        match = _KEY.match(line)
        if match is None:
            if current == "REPLY":
                reply.append(line)
            continue
        key, rest = match.group(1).upper(), match.group(2).strip()
        current = key
        if key == "REPLY":
            reply.append(rest)
        elif key == "DIRECTIVE" and rest:
            body, _, to = rest.partition("|")
            to = re.sub(r"^\s*TO\s*:\s*", "", to, flags=re.IGNORECASE)
            who = tuple(h for h in (part.strip().upper() for part in to.split(",")) if h in handles)
            if len(body.strip()) >= 4:
                directives.append((body.strip(), who or ("all",)))
        elif key == "REVOKE":
            revokes += re.findall(r"DIR-\d+", rest.upper())
        elif key == "ASK":
            handle, _, question = rest.partition(":")
            handle = handle.strip().upper()
            if handle in handles and handle != MANAGER_HANDLE and question.strip():
                asks.append((handle, question.strip()))
    return Plan(
        reply="\n".join(reply).strip(),
        directives=tuple(directives[:3]),
        revokes=tuple(dict.fromkeys(revokes)),
        asks=tuple(asks[:MAX_ASKS]),
    )


def manager_ref(session: Session) -> str | None:
    from aurelis.agents.tables import Agent

    ref = session.execute(
        sa.select(Agent.ref).where(Agent.handle == MANAGER_HANDLE, Agent.retired_at.is_(None))
    ).scalar_one_or_none()
    return None if ref is None else str(ref)


def _situation(session: Session, now: dt.datetime) -> str:
    """The whole company, as the Manager sees it before it answers."""
    from aurelis.manager.directives import active
    from aurelis.mandate.tables import MandateAssessment
    from aurelis.service.tables import DataGrant
    from aurelis.station.activity import activity
    from aurelis.station.health import company_health

    health = company_health(session, now)
    lines = [f"Health: {health.headline} {health.detail}"]
    latest = session.execute(
        sa.select(MandateAssessment).order_by(MandateAssessment.assessed_at.desc()).limit(1)
    ).scalar_one_or_none()
    if latest is not None:
        lines.append(
            f"Ready for real money: {latest.verdict} ({latest.met} of {latest.criteria} "
            "conditions met)"
        )
    grants = session.execute(sa.select(DataGrant).where(DataGrant.revoked_at.is_(None))).scalars()
    data = [
        f"{g.ref} {g.source} ({g.desk} desk, {len(g.instruments or [])} instrument(s))"
        for g in grants
    ]
    lines.append("Data the company may read: " + ("; ".join(data) or "none granted"))
    lines.append(
        "Desks with no price feed of their own (news only, if any): equities, fx, futures, "
        "commodities, options. Opening one needs a data grant from the operator."
    )
    directives = active(session)
    lines.append(
        "Active directives: "
        + ("; ".join(f"{d.ref} (for {d.for_whom()}): {d.text}" for d in directives) or "none")
    )
    acts = activity(session, now)
    staff = sorted(acts.values(), key=lambda a: a.handle)
    lines.append("Staff (handle, department, last thing they did):")
    lines += [
        f"- {a.handle} ({a.department.replace('_', ' ')}): {a.last_line[:140] or 'nothing yet'}"
        for a in staff
    ]
    return "\n".join(lines)


def _consult(
    runtime: Any, manager: str, handle: str, question: str, *, at: dt.datetime
) -> tuple[str, str]:
    """Ask one colleague on the operator's behalf: a real message each way (M64)."""
    from aurelis.collab.consult import consult

    return consult(
        runtime,
        asker=manager,
        handle=handle,
        question=question,
        preface="The Company Manager is asking you on behalf of the operator.",
        at=at,
    )


def _model_of(runtime: Any, manager: Any) -> str:
    from aurelis.platform.llm.routing import model_for

    tier = (
        manager.authority.tier if manager.authority.tier is not ModelTier.NONE else ModelTier.HIGH
    )
    return str(model_for(runtime.provider.name, tier))


def _ask_model(runtime: Any, session: Session, manager: Any, system: str, prompt: str) -> str:
    from aurelis.platform.llm.routing import model_for
    from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

    tier = (
        manager.authority.tier if manager.authority.tier is not ModelTier.NONE else ModelTier.HIGH
    )
    model_id = model_for(runtime.provider.name, tier)
    response = runtime.provider.complete(
        session,
        LlmRequest(
            model=ModelRef(
                provider=runtime.provider.name, model=model_id, tier=tier, max_tokens=1200
            ),
            system=system,
            messages=(Message("user", prompt),),
            actor=manager.ref,
        ),
    )
    return str(response.text).strip()


def manage(runtime: Any, text: str, *, at: dt.datetime | None = None) -> tuple[Exchange, Done]:
    """The operator says ``text`` to the Manager; it acts on it and reports back."""
    from aurelis.agents.tables import Agent
    from aurelis.brain.briefing import briefing, system_with_brain
    from aurelis.judgement.seat import identity_of
    from aurelis.manager.directives import issue, revoke

    text = text.strip()
    if not text:
        raise ValueError("say something")
    moment = at or runtime.clock.now()
    done = Done()

    with runtime.database.session() as session:
        ref = manager_ref(session)
        if ref is None:
            raise KeyError("the company has no Company Manager on the payroll")
        manager = _staffed(runtime, session, ref)
        earlier = thread(session, ref, limit=HISTORY)
        question = _turn(session, agent_ref=ref, speaker="operator", text=text, at=moment)
        runtime.ledger.append(
            session,
            kind=EventKind.CHAT_ASKED,
            actor=Actor.OPERATOR,
            subject=ref,
            payload={"turn": question.ref, "agent": ref, "text": text[:300]},
            at=moment,
        )
        session.expunge(question)

    try:
        with runtime.database.session() as session:
            handles = {
                str(h)
                for h in session.execute(
                    sa.select(Agent.handle).where(Agent.retired_at.is_(None))
                ).scalars()
            }
            system = system_with_brain(
                MANAGER_SYSTEM, identity_of(manager, session), briefing(session)
            )
            so_far = _conversation(earlier, manager.handle)
            prompt = (
                f"The company right now:\n{_situation(session, moment)}\n\n"
                + (f"The conversation so far:\n{so_far}\n\n" if so_far else "")
                + f"The operator says: {text}"
            )
            first = _ask_model(runtime, session, manager, system, prompt)
        plan = parse(first, handles)

        for handle, asked in plan.asks:
            _, said = _consult(runtime, ref, handle, asked, at=moment)
            done.asked.append((handle, asked, said))

        reply = plan.reply
        if done.asked:
            heard = "\n".join(f"{h} answered: {a}" for h, _, a in done.asked)
            with runtime.database.session() as session:
                second = _ask_model(
                    runtime,
                    session,
                    manager,
                    system,
                    f"{prompt}\n\nYou asked colleagues, and they answered:\n{heard}\n\n"
                    "Now write your report to the operator in plain words, starting with "
                    "REPLY:. Do not write DIRECTIVE, REVOKE or ASK lines this time.",
                )
            reply = parse(second, handles).reply or reply

        with runtime.database.session() as session:
            for body, audience in plan.directives:
                row = issue(
                    session,
                    runtime.ledger,
                    text=body,
                    audience=audience,
                    manager_ref=ref,
                    because=question.ref,
                    at=moment,
                )
                who = "everyone" if "all" in audience else ", ".join(audience)
                done.issued.append((row.ref, who, row.text))
            for target in plan.revokes:
                if revoke(
                    session,
                    runtime.ledger,
                    ref=target,
                    manager_ref=ref,
                    because=question.ref,
                    at=moment,
                ):
                    done.revoked.append(target)
            full = (reply or "(no reply)") + (
                "\n\nWhat I did:\n" + "\n".join(done.lines()) if done.lines() else ""
            )
            answer = _turn(
                session,
                agent_ref=ref,
                speaker="agent",
                text=full,
                at=runtime.clock.now(),
                in_reply_to=question.ref,
                model=_model_of(runtime, manager),
            )
            runtime.ledger.append(
                session,
                kind=EventKind.CHAT_ANSWERED,
                actor=ref,
                subject=ref,
                payload={
                    "turn": answer.ref,
                    "in_reply_to": question.ref,
                    "text": full[:300],
                    "directives": [r for r, _, _ in done.issued],
                    "revoked": done.revoked,
                    "asked": [h for h, _, _ in done.asked],
                },
                at=answer.said_at,
            )
            session.expunge(answer)
    except Exception as error:  # noqa: BLE001 - the operator's line stands; say why no answer
        return Exchange(question, None, f"{type(error).__name__}: {error}"), done
    return Exchange(question, answer), done
