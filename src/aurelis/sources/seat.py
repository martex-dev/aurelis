"""The seat where an agent chooses which sources the company reads.

The operator's constraint is that the company read only free, official,
keyless sources; the brief's is that the agents decide what they need. So
the catalogue is fixed by a person and the choice inside it is an agent's:
a Market Intelligence agent is shown every source with what it covers, the
instruments the company follows, and what is already being read, and states
which sources it wants and why, or ``none`` and why. Every answer is a row
and a ledger event, the same as a stated or declined mechanism.

The service reads the union of what was wanted, under a grant for the source
class that a person recorded once. An agent cannot add a source to the
catalogue, and the catalogue cannot contain anything that needs a key.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.interpret import render_material
from aurelis.core.canonical import sha256_of
from aurelis.core.enums import Actor, EventKind, ModelTier
from aurelis.core.ids import RefKind, uuid7
from aurelis.intel.news import CATALOGUE, Source
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.llm.routing import model_for
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef
from aurelis.sources.tables import SourceRequest

__all__ = [
    "SOURCE_FORM",
    "SYSTEM",
    "SourceRefused",
    "active_sources",
    "answered_on",
    "catalogue_digest",
    "request_sources",
    "seat_sources",
]

SYSTEM = (
    "You are a market-intelligence analyst at a quantitative company. The "
    "company reads only free, official, keyless sources, and it reads only what "
    "its analysts ask for. You are shown the catalogue of sources it could read, "
    "what each covers, and the instruments the company follows. Ask for the "
    "sources whose content bears on those instruments and on the mechanisms the "
    "company tests -- listings, halts, flows, crowding, forced sellers -- and say "
    "why. Ask for none if none would. A source the company reads costs a fetch "
    "every hour and fills the event stream the judges and the miner read, so a "
    "source that adds noise is worse than no source."
)

SOURCE_FORM = (
    "Which of these sources should the company read? Reply in exactly this form "
    "and nothing else:\n"
    "SOURCES: <names from the catalogue, comma-separated, or none>\n"
    "BECAUSE: <why, in one or two sentences>\n"
)

_FIELD = re.compile(r"^\s*(SOURCES|BECAUSE)\s*:\s*(.*)$", re.I)


class SourceRefused(ValueError):
    """The reply could not be read, or named a source that is not in the catalogue."""


@dataclass(frozen=True, slots=True)
class SourceChoice:
    wanted: tuple[str, ...]
    because: str

    @property
    def declined(self) -> bool:
        return not self.wanted


def catalogue_digest(catalogue: dict[str, Source] | None = None) -> str:
    return sha256_of(sorted((catalogue or CATALOGUE).keys()))


def _parse(text: str, catalogue: dict[str, Source]) -> SourceChoice:
    fields: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).upper()
            fields[current] = match.group(2).strip()
        elif current == "BECAUSE" and line.strip():
            fields[current] = f"{fields[current]} {line.strip()}".strip()
    raw = fields.get("SOURCES", "").strip()
    because = fields.get("BECAUSE", "").strip()
    if not raw:
        raise SourceRefused("the reply names no SOURCES line")
    if len(because) <= 10:
        raise SourceRefused("a choice of sources without a reason is not a choice")
    if raw.lower() == "none":
        return SourceChoice((), because)
    names = tuple(dict.fromkeys(n.strip().lower() for n in raw.split(",") if n.strip()))
    unknown = [n for n in names if n not in catalogue]
    if unknown:
        raise SourceRefused(f"not in the catalogue: {', '.join(unknown)}")
    return SourceChoice(names, because)


def active_sources(session: Session) -> list[str]:
    """Sources whose most recent answer, from any agent, was to want them."""
    rows = session.execute(
        sa.select(SourceRequest).order_by(
            SourceRequest.requested_at.desc(), SourceRequest.ref.desc()
        )
    ).scalars()
    latest: dict[str, bool] = {}
    for row in rows:
        latest.setdefault(row.source, bool(row.wanted))
    return sorted(name for name, wanted in latest.items() if wanted and name in CATALOGUE)


def answered_on(session: Session, agent_ref: str, digest: str) -> bool:
    """Whether this agent has already answered on this catalogue."""
    return (
        session.execute(
            sa.select(sa.func.count()).where(
                SourceRequest.agent_ref == agent_ref, SourceRequest.catalogue_digest == digest
            )
        ).scalar_one()
        > 0
    )


def request_sources(
    provider: Any,
    session: Session,
    *,
    agent_ref: str,
    instruments: tuple[str, ...],
    catalogue: dict[str, Source] | None = None,
    tier: ModelTier = ModelTier.MID,
    identity: str = "",
    task_ref: str | None = None,
    ledger: Any = None,
    at: dt.datetime | None = None,
    clock: Any = None,
) -> list[SourceRequest]:
    """Show the agent the catalogue and record what it asked for, or its decline."""
    the_catalogue = catalogue or CATALOGUE
    moment = at or (clock.now() if clock is not None else dt.datetime.now(dt.UTC))
    digest = catalogue_digest(the_catalogue)
    already = active_sources(session)
    material = {
        "catalogue": {name: source.describe() for name, source in the_catalogue.items()},
        "instruments_followed": list(instruments),
        "already_read": already or ["nothing yet"],
        "note": (
            "Every source above is free, official and keyless; that is why it is "
            "in the catalogue. Nothing outside it can be asked for."
        ),
    }
    system = f"{SYSTEM}\n\n{identity}" if identity else SYSTEM
    rendered = f"{render_material(material)}\n\n{SOURCE_FORM}"
    model_id = model_for(provider.name, tier)
    response = provider.complete(
        session,
        LlmRequest(
            model=ModelRef(provider=provider.name, model=model_id, tier=tier, max_tokens=300),
            system=system,
            messages=(Message("user", rendered),),
            actor=agent_ref,
            task_ref=task_ref,
        ),
    )
    choice = _parse(response.text, the_catalogue)
    rows: list[SourceRequest] = []
    if choice.declined:
        row = SourceRequest(
            request_id=uuid7(),
            ref=allocate_ref(session, RefKind.SOURCE_REQUEST),
            agent_ref=agent_ref,
            source="none",
            wanted=False,
            reason=choice.because,
            catalogue_digest=digest,
            requested_at=moment,
        )
        session.add(row)
        session.flush()
        rows.append(row)
        if ledger is not None:
            ledger.append(
                session,
                kind=EventKind.SOURCE_DECLINED,
                actor=agent_ref,
                subject=row.ref,
                payload={"because": choice.because[:400], "catalogue": digest[:16]},
                at=moment,
            )
        return rows
    for name in choice.wanted:
        row = SourceRequest(
            request_id=uuid7(),
            ref=allocate_ref(session, RefKind.SOURCE_REQUEST),
            agent_ref=agent_ref,
            source=name,
            wanted=True,
            reason=choice.because,
            catalogue_digest=digest,
            requested_at=moment,
        )
        session.add(row)
        session.flush()
        rows.append(row)
        if ledger is not None:
            ledger.append(
                session,
                kind=EventKind.SOURCE_REQUESTED,
                actor=agent_ref,
                subject=row.ref,
                payload={
                    "source": name,
                    "url": the_catalogue[name].url,
                    "because": choice.because[:400],
                    "catalogue": digest[:16],
                },
                at=moment,
            )
    return rows


def seat_sources(
    runtime: Any, *, agent_handle: str, at: dt.datetime | None = None
) -> list[SourceRequest]:
    """Put a named agent in the sources seat under a task."""
    from aurelis.judgement.seat import identity_of
    from aurelis.service.grants import Grants

    moment = at or runtime.clock.now()
    with runtime.database.session() as session:
        seated = runtime.roster.by_handle(session, agent_handle)
        instruments: list[str] = []
        for grant in Grants.active(session):
            for symbol in grant.instruments:
                if str(symbol) not in instruments:
                    instruments.append(str(symbol))
        task = runtime.queue.enqueue(
            session,
            kind="sources.choice",
            assignee=seated.ref,
            payload={"catalogue": catalogue_digest()[:16]},
            actor=Actor.SYSTEM,
            at=moment,
        )
        claimed = runtime.queue.claim(session, worker=seated.ref, at=moment)
        task_ref = claimed.ref if claimed is not None else task.ref
        try:
            rows = request_sources(
                runtime.provider,
                session,
                agent_ref=seated.ref,
                instruments=tuple(instruments),
                tier=seated.authority.tier
                if seated.authority.tier is not ModelTier.NONE
                else ModelTier.MID,
                identity=identity_of(seated),
                task_ref=task_ref,
                ledger=runtime.ledger,
                at=moment,
            )
        except SourceRefused as error:
            if claimed is not None:
                runtime.queue.fail(session, claimed, error=str(error)[:200], at=moment)
            raise
        if claimed is not None:
            runtime.queue.succeed(
                session,
                claimed,
                result_digest=sha256_of({"requested": [r.source for r in rows if r.wanted]}),
                at=moment,
            )
        return rows
