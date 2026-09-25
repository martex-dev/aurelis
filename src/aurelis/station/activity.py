"""What the company is doing now, read off the ledger (M52).

Until M52 the facility lit a room only when one of its agents had
``state = working``. The service's seats never set that: a seat claims a
task, calls the model and seals a view inside one transaction, so by the
time a page reads the row the agent is idle again. The building showed
IDLE everywhere while the agents sealed twenty views an hour.

Everything an agent does is an event with its ref as the actor. So activity
is read from the ledger instead:

* an agent is **working** if it acted in the last ten minutes,
* a room is **working** if any of its agents is,
* the current wake is **in progress** if a ``service.woke`` has no finished
  cycle after it,
* the feed says what each event was, in a line built from the event's own
  payload, never paraphrased.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent
from aurelis.platform.db.tables import Event

__all__ = [
    "ACTIVE_WINDOW",
    "KIND_WORDS",
    "AgentActivity",
    "FeedLine",
    "WakeState",
    "activity",
    "describe",
    "feed",
    "wake_state",
]

ACTIVE_WINDOW = dt.timedelta(minutes=10)
"""An agent that acted this recently is shown working."""

QUIET_KINDS = frozenset(
    {"artifact.stored", "world.event_recorded", "task.enqueued", "gov.mandate_assessed"}
)
"""Bookkeeping: recorded, counted, but not a line in the feed on its own."""

ROUTINE_KINDS = frozenset({"model.called", "intel.market_snapshot_ingested"})
"""The heartbeat: a model call is an agent thinking, a snapshot a recording.
They make an agent or a wake *active* and are counted, but the feed and an
agent's last line show what the thinking decided."""


KIND_WORDS: dict[str, str] = {
    "model.called": "model calls",
    "judgement.thesis_sealed": "views sealed",
    "judgement.thesis_declined": "declines",
    "judgement.thesis_refused": "refusals",
    "judgement.thesis_scored": "views scored",
    "brain.noted": "notes",
    "trading.order_filled": "paper fills",
    "risk.assessed": "risk checks",
    "mechanism.traded": "scheme trades",
    "ops.alert_raised": "alerts",
    "source.requested": "source requests",
    "intel.market_snapshot_ingested": "recordings",
}


def hour_words(counts: Counter[str]) -> str:
    """``{"model.called": 27}`` as ``27 model calls``; bookkeeping left out."""
    shown = [
        f"{n} {KIND_WORDS.get(kind, kind.split('.')[-1].replace('_', ' '))}"
        for kind, n in counts.most_common()
        if kind not in QUIET_KINDS
    ]
    return ", ".join(shown[:3])


def _aware(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def _ago(now: dt.datetime, then: dt.datetime) -> str:
    seconds = int((now - _aware(then)).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m ago"
    return f"{seconds // 86400}d ago"


def describe(kind: str, subject: str | None, payload: dict[str, Any]) -> str:
    """One plain line for one event, from its own payload."""
    p = payload
    s = subject or ""
    if kind == "judgement.thesis_sealed":
        return (
            f"sealed a view: {p.get('instrument')} {p.get('direction')} over "
            f"{p.get('horizon_hours')}h at {p.get('confidence')} ({s})"
        )
    if kind == "judgement.thesis_declined":
        stage = p.get("stage", "")
        why = str(p.get("reasoning") or "")[:140]
        where = "no market" if stage == "market" else stage
        return f"declined ({where}): {why}" if why else f"declined ({where})"
    if kind == "judgement.thesis_refused":
        where = p.get("instrument") or p.get("stage")
        return f"refused at {where}: {str(p.get('cause', ''))[:140]}"
    if kind == "judgement.thesis_scored":
        verdict = "right" if p.get("hit") else "wrong"
        return (
            f"{p.get('agent')}'s view on {p.get('instrument')} ({p.get('direction')}) "
            f"was {verdict}, Brier {p.get('brier')} ({s})"
        )
    if kind == "brain.noted":
        return f"left a note: {str(p.get('text', ''))[:160]}"
    if kind == "model.called":
        return f"thought ({p.get('model')}, {p.get('tokens_in')} in / {p.get('tokens_out')} out)"
    if kind == "mechanism.predicted":
        return f"{s} sealed {p.get('sealed')} prediction(s) on {p.get('trigger')}"
    if kind == "mechanism.traded":
        return (
            f"{s} on paper: opened {p.get('opened')}, closed {p.get('closed')}, "
            f"refused {p.get('refused')}"
        )
    if kind == "mechanism.stated":
        return f"stated a mechanism: {p.get('title', s)}"
    if kind == "mechanism.retired":
        return f"{s} retired: {str(p.get('reason', ''))[:140]}"
    if kind == "trading.order_filled":
        return (
            f"paper fill: {p.get('side')} {p.get('symbol')} at {p.get('price')} ({p.get('broker')})"
        )
    if kind == "risk.assessed":
        return f"risk {p.get('decision')}: desired {p.get('desired')}, allowed {p.get('allowed')}"
    if kind == "trading.paper_cycle_ran":
        return (
            f"paper cycle: {p.get('proposed')} proposed, {p.get('executed')} executed, "
            f"{p.get('refused')} refused"
        )
    if kind == "trading.post_trade_analysed":
        return (
            f"post-trade: filled at {p.get('fill_price')} against "
            f"{p.get('expected_price')} expected ({p.get('slippage_bps')} bps)"
        )
    if kind == "trading.approved":
        return f"approved {s}: final {p.get('final')}"
    if kind == "ops.alert_raised":
        return f"alert ({p.get('severity')}): {str(p.get('message', ''))[:160]}"
    if kind == "service.woke":
        return f"the service woke ({s}), {len(p.get('fetched') or [])} recording(s) fetched"
    if kind == "service.started":
        return f"the service started: {p.get('calls_per_day')} model calls a day"
    if kind == "source.requested":
        return f"asked to read {p.get('source')}: {str(p.get('because', ''))[:120]}"
    if kind == "source.declined":
        return f"declined every source: {str(p.get('because', ''))[:120]}"
    if kind in ("social.followed", "social.dropped"):
        verb = "followed" if kind == "social.followed" else "dropped"
        return f"{verb} {p.get('platform')}:{p.get('handle')}: {str(p.get('because', ''))[:100]}"
    if kind == "mechanism.suspended":
        return (
            f"suspended {s} from paper: lost {p.get('pnl')} after fees over "
            f"{p.get('episodes')} episode(s), {p.get('lost')} lost and {p.get('won')} won"
        )
    if kind == "social.curated":
        measured = f"{p.get('measured')} of {p.get('voices')} voice(s) measured"
        if p.get("refused"):
            return f"curation refused ({measured}): {str(p.get('refused'))[:100]}"
        if not p.get("asked"):
            if p.get("offered_follow") or p.get("offered_drop"):
                return f"curation: {measured}, no market-intelligence agent to ask"
            return f"curation: {measured}, none eligible to follow or drop"
        moved = [f"followed {v}" for v in p.get("followed") or []] + [
            f"dropped {v}" for v in p.get("dropped") or []
        ]
        return (
            f"curated whom to follow ({measured}): {', '.join(moved) or 'kept every voice'}: "
            f"{str(p.get('because', ''))[:100]}"
        )
    if kind == "agent.method_adopted":
        return (
            f"{p.get('agent')} adopted method v{p.get('version')} by {p.get('authored_by')}: "
            f"{str(p.get('method', ''))[:120]}"
        )
    if kind == "org.evolution_ran":
        fitness = p.get("fitness") or []
        failing = [f.get("agent") for f in fitness if f.get("verdict") == "failing"]
        return (
            f"evolution measured {len(fitness)} method(s); failing: {', '.join(failing) or 'none'}"
        )
    if kind == "intel.market_snapshot_ingested":
        return f"recorded {p.get('symbol')} ({p.get('bars')} bars from {p.get('source')})"
    if kind == "gov.mandate_assessed":
        return f"mandate: {p.get('verdict')} ({p.get('met')}/{p.get('criteria')} conditions met)"
    shown = [
        f"{k}={v}" for k, v in p.items() if isinstance(v, (str, int, bool)) and len(str(v)) <= 48
    ]
    return f"{kind}: {', '.join(shown[:3])}".rstrip(": ")


@dataclass(frozen=True, slots=True)
class AgentActivity:
    ref: str
    handle: str
    department: str
    last_at: dt.datetime | None
    last_line: str
    last_hour: Counter[str] = field(default_factory=Counter)

    def working(self, now: dt.datetime) -> bool:
        return self.last_at is not None and now - _aware(self.last_at) <= ACTIVE_WINDOW


def activity(session: Session, now: dt.datetime) -> dict[str, AgentActivity]:
    """Every agent's newest act and its last hour, by ref."""
    now = _aware(now)
    agents = session.execute(sa.select(Agent.ref, Agent.handle, Agent.department)).all()
    refs = [a.ref for a in agents]
    newest: dict[str, tuple[dt.datetime, str]] = {}
    hour: dict[str, Counter[str]] = {ref: Counter() for ref in refs}
    rows = session.execute(
        sa.select(Event.actor, Event.kind, Event.subject, Event.payload, Event.created_at)
        .where(Event.actor.in_(refs), Event.created_at >= now - dt.timedelta(hours=24))
        .order_by(Event.seq.desc())
    ).all()
    latest: dict[str, dt.datetime] = {}
    for actor, kind, subject, payload, at in rows:
        if kind not in QUIET_KINDS:
            latest.setdefault(actor, at)
        if actor not in newest and kind not in QUIET_KINDS | ROUTINE_KINDS:
            newest[actor] = (at, describe(kind, subject, dict(payload or {})))
        if _aware(at) >= now - dt.timedelta(hours=1):
            hour[actor][kind] += 1
    missing = [r for r in refs if r not in newest]
    if missing:
        older = session.execute(
            sa.select(Event.actor, sa.func.max(Event.created_at))
            .where(Event.actor.in_(missing))
            .group_by(Event.actor)
        ).all()
        for actor, at in older:
            newest[actor] = (at, "last acted over a day ago")
    return {
        a.ref: AgentActivity(
            ref=a.ref,
            handle=a.handle,
            department=str(a.department),
            last_at=latest.get(a.ref) or newest.get(a.ref, (None, ""))[0],
            last_line=newest.get(a.ref, (None, "has not acted yet"))[1],
            last_hour=hour.get(a.ref, Counter()),
        )
        for a in agents
    }


@dataclass(frozen=True, slots=True)
class WakeState:
    in_progress: bool
    wake_ref: str
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    calls_this_wake: int
    this_wake: Counter[str]
    last_note: str

    def headline(self, now: dt.datetime) -> str:
        if self.started_at is None:
            return "The service has not woken yet."
        if self.in_progress:
            return (
                f"A wake is in progress, started {_ago(now, self.started_at)}: "
                f"{self.calls_this_wake} model call(s) so far."
            )
        ended = _ago(now, self.finished_at) if self.finished_at else "earlier"
        return f"Between wakes. The last, {self.wake_ref}, ended {ended}."


def wake_state(session: Session, now: dt.datetime) -> WakeState:
    """The service's current wake, or the last one, and what it has done."""
    from aurelis.service.tables import ServiceCycle

    woke = session.execute(
        sa.select(Event.subject, Event.created_at, Event.seq)
        .where(Event.kind == "service.woke")
        .order_by(Event.seq.desc())
        .limit(1)
    ).first()
    cycle = session.execute(
        sa.select(ServiceCycle).order_by(ServiceCycle.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    if woke is None:
        return WakeState(False, "", None, None, 0, Counter(), "")
    wake_ref, started_at, seq = woke
    # ``service.woke`` is appended when a wake ends. Recordings or model calls
    # after it are the next wake, under way.
    under_way = session.execute(
        sa.select(sa.func.min(Event.created_at)).where(
            Event.seq > seq, Event.kind.in_(ROUTINE_KINDS | {"service.started"})
        )
    ).scalar_one_or_none()
    if under_way is not None:
        started_at, wake_ref = under_way, "the next wake"
    finished = under_way is None and cycle is not None and cycle.finished_at is not None
    counts: Counter[str] = Counter(
        {
            str(kind): int(n)
            for kind, n in session.execute(
                sa.select(Event.kind, sa.func.count()).where(Event.seq > seq).group_by(Event.kind)
            ).all()
        }
    )
    return WakeState(
        in_progress=not finished,
        wake_ref=str(wake_ref),
        started_at=started_at,
        finished_at=cycle.finished_at if finished and cycle is not None else None,
        calls_this_wake=counts.get("model.called", 0),
        this_wake=counts,
        last_note=(cycle.note if cycle is not None and cycle.note else ""),
    )


@dataclass(frozen=True, slots=True)
class FeedLine:
    seq: int
    at: dt.datetime
    actor: str
    who: str
    line: str
    href: str


def feed(session: Session, *, limit: int = 60, since: int = 0) -> list[FeedLine]:
    """The newest events worth a line, newest first; bookkeeping left out."""
    handles: dict[str, str] = {
        str(ref): str(handle)
        for ref, handle in session.execute(sa.select(Agent.ref, Agent.handle)).all()
    }
    query = sa.select(Event).where(Event.kind.not_in(QUIET_KINDS | ROUTINE_KINDS))
    if since:
        query = query.where(Event.seq > since)
    rows = session.execute(query.order_by(Event.seq.desc()).limit(limit)).scalars()
    out: list[FeedLine] = []
    for row in rows:
        who = handles.get(row.actor, row.actor)
        subject = row.subject or ""
        href = ""
        if subject.startswith("THS-"):
            href = f"/thesis/{subject}"
        elif subject.startswith("MEC-"):
            href = f"/mechanism/{subject}"
        elif row.actor in handles:
            href = f"/agent/{row.actor}"
        out.append(
            FeedLine(
                seq=row.seq,
                at=row.created_at,
                actor=row.actor,
                who=who,
                line=describe(row.kind, row.subject, dict(row.payload or {})),
                href=href,
            )
        )
    return out
