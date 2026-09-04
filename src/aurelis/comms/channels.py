"""Channels and posting.

Two rules, both enforced rather than described.

**Posting requires the MESSAGE write scope**, checked by a database trigger, so
an agent whose charters do not grant it cannot post even through raw SQL.

**Reading a channel requires membership.** An agent that could read any channel
would collapse the information asymmetry the research design depends on — a
critic that has already read the author's channel is reviewing a conclusion
rather than evidence.

Every message is also stored as a content-addressed artifact, so a message is
citable in exactly the same way as any other artifact, and quoting one in a
meeting three weeks later resolves to the bytes that were actually sent.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.comms.tables import Channel, ChannelKind, ChannelMember, Message, MessageKind, Priority
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.errors import PermissionDenied
from aurelis.core.ids import RefKind, uuid7
from aurelis.org.departments import DEPARTMENTS
from aurelis.org.desks import DESKS
from aurelis.platform.artifacts.store import ArtifactStore
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["COMPANY_CHANNELS", "Comms"]

COMPANY_CHANNELS: tuple[tuple[str, str], ...] = (
    ("all-hands", "Everyone. Company state and direction."),
    ("alerts", "Anything that needs attention now."),
    ("findings", "Results the company believes."),
    ("graveyard", "Results the company killed, and why."),
)


class Comms:
    """Creates channels, manages membership, and carries messages."""

    __slots__ = ("_artifacts", "_clock", "_ledger")

    def __init__(
        self,
        artifacts: ArtifactStore,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    # ------------------------------------------------------------- channels

    def ensure_channels(self, session: Session, *, at: dt.datetime | None = None) -> int:
        """Create the standing channels. Idempotent.

        Derived from the org registry rather than listed separately: a
        department that exists always has somewhere to talk, and a desk that
        opens gets a channel without anyone remembering to add one.
        """
        moment = at or self._clock.now()
        existing = set(session.execute(sa.select(Channel.channel_id)).scalars())
        created = 0

        wanted: list[tuple[str, ChannelKind, str, str]] = [
            (f"company-{name}", ChannelKind.COMPANY, name, purpose)
            for name, purpose in COMPANY_CHANNELS
        ]
        wanted += [
            (f"dept-{spec.department.value}", ChannelKind.DEPARTMENT, spec.name, spec.owns)
            for spec in DEPARTMENTS.values()
        ]
        wanted += [
            (f"desk-{desk.value}", ChannelKind.DESK, spec.name, f"{spec.name} desk")
            for desk, spec in DESKS.items()
        ]

        for channel_id, kind, name, purpose in wanted:
            if channel_id in existing:
                continue
            session.add(
                Channel(
                    channel_id=channel_id,
                    kind=kind.value,
                    name=name,
                    purpose=purpose,
                    created_at=moment,
                )
            )
            created += 1

        session.flush()
        if created:
            self._ledger.append(
                session,
                kind=EventKind.CHANNEL_CREATED,
                payload={"created": created},
                at=moment,
            )
        return created

    def join(
        self, session: Session, channel_id: str, agent_ref: str, *, at: dt.datetime | None = None
    ) -> None:
        existing = session.get(ChannelMember, (channel_id, agent_ref))
        if existing is not None:
            return
        session.add(
            ChannelMember(
                channel_id=channel_id,
                agent_ref=agent_ref,
                joined_at=at or self._clock.now(),
            )
        )
        session.flush()

    def enrol(
        self,
        session: Session,
        agent_ref: str,
        *,
        department: str,
        desk: str | None,
        at: dt.datetime | None = None,
    ) -> list[str]:
        """Put an agent in the channels its posting implies.

        Its department, its desk if it has one, and the company-wide channels.
        Anything narrower is a mission or team channel it is added to when the
        work exists.
        """
        channels = [f"company-{name}" for name, _ in COMPANY_CHANNELS]
        channels.append(f"dept-{department}")
        if desk:
            channels.append(f"desk-{desk}")
        for channel_id in channels:
            self.join(session, channel_id, agent_ref, at=at)
        return channels

    def is_member(self, session: Session, channel_id: str, agent_ref: str) -> bool:
        return session.get(ChannelMember, (channel_id, agent_ref)) is not None

    # ------------------------------------------------------------- messages

    def post(
        self,
        session: Session,
        *,
        from_agent: str,
        kind: MessageKind,
        subject: str,
        body: str,
        channel_id: str | None = None,
        to_agents: tuple[str, ...] = (),
        claims: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        desk: str | None = None,
        task_ref: str | None = None,
        priority: Priority = Priority.NORMAL,
        requires_response: bool = False,
        at: dt.datetime | None = None,
    ) -> Message:
        """Post a message.

        The write-scope trigger is the authority check; this method does not
        re-implement it. What it *does* check is channel membership, which the
        database cannot express as cleanly, and it records the refusal before
        raising.
        """
        moment = at or self._clock.now()

        if channel_id is not None and not self.is_member(session, channel_id, from_agent):
            self._ledger.append(
                session,
                kind=EventKind.PERMISSION_DENIED,
                actor=from_agent,
                subject=channel_id,
                payload={"action": "post", "reason": "not a member of this channel"},
                at=moment,
            )
            raise PermissionDenied(from_agent, "post to", channel_id)

        ref = allocate_ref(session, RefKind.MESSAGE)
        stored = self._artifacts.put_json(
            session,
            {
                "from": from_agent,
                "kind": kind.value,
                "subject": subject,
                "body": body,
                "claims": list(claims),
                "evidence_refs": list(evidence_refs),
            },
            kind="message",
            produced_by=from_agent,
            actor=from_agent,
        )

        message = Message(
            message_id=uuid7(),
            ref=ref,
            from_agent=from_agent,
            channel_id=channel_id,
            to_agents=list(to_agents),
            kind=kind.value,
            priority=priority.value,
            subject=subject[:256],
            body=body,
            claims=list(claims),
            evidence_refs=list(evidence_refs),
            desk=desk,
            task_ref=task_ref,
            requires_response=requires_response,
            artifact_digest=stored.digest,
            created_at=moment,
        )
        session.add(message)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.MESSAGE_POSTED,
            actor=from_agent,
            subject=channel_id or (to_agents[0] if to_agents else None),
            payload={
                "message": ref,
                "kind": kind.value,
                "subject": subject[:120],
                "claims": len(claims),
                "evidence_refs": len(evidence_refs),
                "artifact": stored.digest[:12],
            },
            at=moment,
        )
        return message

    def read(
        self, session: Session, *, channel_id: str, agent_ref: str, limit: int = 20
    ) -> list[Message]:
        """Read a channel, refusing a non-member."""
        if not self.is_member(session, channel_id, agent_ref):
            raise PermissionDenied(agent_ref, "read", channel_id)
        rows = (
            session.execute(
                sa.select(Message)
                .where(Message.channel_id == channel_id)
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return list(reversed(rows))

    def inbox(self, session: Session, agent_ref: str, limit: int = 20) -> list[Message]:
        """Messages addressed to this agent directly."""
        rows = (
            session.execute(
                sa.select(Message).order_by(Message.created_at.desc()).limit(limit * 4)
            )
            .scalars()
            .all()
        )
        addressed: list[Message] = []
        for row in rows:
            recipients: list[Any] = row.to_agents or []
            if agent_ref in recipients:
                addressed.append(row)
            if len(addressed) >= limit:
                break
        return list(reversed(addressed))
