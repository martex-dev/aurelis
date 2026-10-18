"""What the Office shows, read off the record (M61).

The map is drawn once per page load. What changes (who is working, what
they just did, whether the company is thinking) is served separately as
JSON, and the page polls it, so the figures move when the record says they
are working and stand still when it says they are not.

Every room's dashboard is a fragment served on demand and opened over the
map. It is built from the same page functions the rest of the station uses,
so a number in the Office is the number on the page it came from.
"""

from __future__ import annotations

import datetime as dt
from html import escape
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.office.art import OfficeAgent, build_of
from aurelis.office.map import CONTROL, ROOMS, OfficeRoom, room_named, room_of

__all__ = [
    "MANAGER_HANDLE",
    "SERVICE_REF",
    "agent_panel",
    "live_state",
    "people",
    "room_panel",
    "tab",
]

MANAGER_HANDLE = "CEO"
"""The Company Manager works in the Control Room, not the Executive Suite: the
room in the middle is where the whole company is watched from (M61), and the
manager is who the operator will talk to there (M63)."""

SERVICE_REF = "SERVICE"
"""The hourly service, drawn as the one figure that is not a person: the
servitor in the Engine Room. It works while a wake is in progress."""


def people(session: Session) -> list[OfficeAgent]:
    """Everybody on the payroll, in the room they work in, and the service."""
    from aurelis.agents.tables import Agent

    rows = session.execute(
        sa.select(Agent.ref, Agent.handle, Agent.department)
        .where(Agent.retired_at.is_(None))
        .order_by(Agent.ref)
    ).all()
    out = [
        OfficeAgent(
            ref=str(ref),
            handle=str(handle),
            room_id=CONTROL if handle == MANAGER_HANDLE else room_of(str(department)),
            build=build_of(str(handle), str(department)),
        )
        for ref, handle, department in rows
    ]
    out.append(OfficeAgent(SERVICE_REF, "SERVICE", "infrastructure", "system"))
    return out


def _ago(now: dt.datetime, then: dt.datetime | None) -> str:
    from aurelis.station.activity import _ago as ago

    return ago(now, then) if then is not None else "never"


def live_state(session: Session, now: dt.datetime) -> dict[str, Any]:
    """Who is working, what each did last, and whether the company is thinking."""
    from aurelis.station.activity import activity, feed, wake_state
    from aurelis.station.health import company_health

    health = company_health(session, now)
    wake = wake_state(session, now)
    acts = activity(session, now)
    agents: dict[str, dict[str, Any]] = {}
    rooms: dict[str, dict[str, Any]] = {
        room.room_id: {"working": 0, "staff": 0, "line": ""} for room in ROOMS
    }
    for person in people(session):
        if person.ref == SERVICE_REF:
            working = wake.in_progress
            line = wake.headline(now)
            last = ""
        else:
            act = acts.get(person.ref)
            working = bool(act and act.working(now))
            line = act.last_line if act else ""
            last = _ago(now, act.last_at if act else None)
        agents[person.ref] = {
            "handle": person.handle,
            "room": person.room_id,
            "working": working,
            "line": line[:180],
            "ago": last,
        }
        room = rooms[person.room_id]
        room["staff"] += 1
        room["working"] += int(working)
        if working and not room["line"]:
            room["line"] = f"{person.handle}: {line[:120]}"
    return {
        "at": now.astimezone(dt.UTC).strftime("%H:%M:%S"),
        "health": {
            "state": health.state,
            "headline": health.headline,
            "detail": health.detail,
            "todo": health.todo,
        },
        "wake": wake.headline(now),
        "agents": agents,
        "rooms": rooms,
        "feed": [
            {"at": f.at.strftime("%H:%M"), "who": f.who, "line": f.line[:200], "href": f.href}
            for f in feed(session, limit=14)
        ],
    }


# ------------------------------------------------------------- dashboards

#: The page each department's room opens as its own tab, beside the brief.
#: It is the part of the station that is about that department's work.
_EXTRA: dict[str, tuple[str, str]] = {
    "market_intelligence": ("voices", "whom the company follows"),
    "quantitative_research": ("lab", "the strategy lab"),
    "strategy_laboratory": ("mechanisms", "mechanisms under test"),
    "portfolio_and_risk": ("mandate", "capital, risk and the path to money"),
    "trading_operations": ("mandate", "the paper book"),
    "executive": ("theses", "every sealed view and its grade"),
    "knowledge_and_memory": ("brain", "the shared brain"),
    "audit_and_governance": ("graveyard", "what failed, and why"),
    "institutional_governance": ("timeline", "the record, newest first"),
    "infrastructure": ("service", "the service and what broke"),
}


def _section(tab: str, body: str, *, hidden: bool = True) -> str:
    return f"<section data-tab='{tab}'{' hidden' if hidden else ''}>{body}</section>"


def _brief(room: OfficeRoom) -> str:
    steps = "".join(f"<li>{escape(step)}</li>" for step in room.steps)
    return (
        f"<p class='plain'>{escape(room.plain)}</p>"
        f"<h2>what happens here</h2><ol class='steps'>{steps}</ol>"
    )


def _crew(session: Session, room_id: str, state: dict[str, Any]) -> str:
    cards = []
    for person in people(session):
        if person.room_id != room_id:
            continue
        live = state["agents"].get(person.ref, {})
        working = live.get("working", False)
        line = live.get("line") or "nothing recorded yet"
        href = "" if person.ref == SERVICE_REF else f" data-agent='{escape(person.ref)}'"
        cards.append(
            f"<button type='button' class='who{' on' if working else ''}'{href}>"
            f"<b>{escape(person.handle)}</b>"
            f"<i>{escape(person.ref)} · {'working now' if working else 'at their post'}</i>"
            f"<span>{escape(line)}</span>"
            f"<span class='ago'>last act: {escape(live.get('ago', ''))}</span></button>"
        )
    if not cards:
        return (
            "<p class='plain sm'>Nobody works here yet. The room is drawn empty because it is.</p>"
        )
    return f"<div class='crew'>{''.join(cards)}</div>"


def _now(state: dict[str, Any], room_id: str) -> str:
    handles = {a["handle"] for a in state["agents"].values() if a["room"] == room_id}
    lines = (
        [f for f in state["feed"] if f["who"] in handles] if room_id != CONTROL else state["feed"]
    )
    if not lines:
        return "<p class='plain sm'>Nothing from this room in the company's recent feed.</p>"
    items = "".join(
        f"<li><span class='t'>{escape(f['at'])}</span><b>{escape(f['who'])}</b>"
        f"<span>{escape(f['line'])}</span></li>"
        for f in lines
    )
    return f"<ul class='feed'>{items}</ul>"


def _page(session: Session, name: str, now: dt.datetime) -> str:
    from aurelis.station import pages

    builders: dict[str, Any] = {
        "lab": lambda: lab_panel(session),
        "voices": lambda: pages.voices_page(session, now=now),
        "mechanisms": lambda: pages.mechanisms_page(session),
        "theses": lambda: pages.theses_page(session, now=now),
        "mandate": lambda: pages.mandate_page(session),
        "missions": lambda: pages.missions_page(session),
        "brain": lambda: pages.brain_page(session),
        "graveyard": lambda: pages.graveyard_page(session),
        "timeline": lambda: pages.timeline_page(session, limit=80),
        "service": lambda: pages.service_page(session),
    }
    try:
        return str(builders[name]())
    except Exception as error:  # noqa: BLE001 - one broken tab must not close the room
        return f"<p class='plain sm'>This tab could not be built: {escape(str(error))}</p>"


def _lazy(name: str) -> str:
    """A tab that is built when it is opened, not when the room is: some of
    the pages behind the tabs read the whole record and take seconds."""
    return f"<div data-src='/office/tab/{escape(name)}'><p class='load'>opening&hellip;</p></div>"


def tab(session: Session, name: str, now: dt.datetime) -> str | None:
    """One lazily opened tab."""
    if name not in {extra for extra, _ in _EXTRA.values()}:
        return None
    return _page(session, name, now)


def _control(session: Session, state: dict[str, Any], now: dt.datetime) -> str:
    from aurelis.mandate.tables import MandateAssessment
    from aurelis.station.pages import _today_counts

    today = _today_counts(session, now)
    latest = session.execute(
        sa.select(MandateAssessment).order_by(MandateAssessment.assessed_at.desc()).limit(1)
    ).scalar_one_or_none()
    working = sum(1 for a in state["agents"].values() if a["working"])
    staff = len(state["agents"])
    health = state["health"]
    tiles = [
        ("working now", f"{working} of {staff}"),
        ("views sealed today", today.get("judgement.thesis_sealed", 0)),
        ("views graded today", today.get("judgement.thesis_scored", 0)),
        ("brain notes today", today.get("brain.noted", 0)),
        ("model calls today", today.get("model.called", 0)),
        (
            "ready for real money?",
            f"{'YES' if latest and latest.verdict == 'ready' else 'not yet'}"
            + (f" · {latest.met} of {latest.criteria}" if latest else ""),
        ),
    ]
    tile_html = "".join(
        f"<div class='tile'><div class='n'>{escape(str(n))}</div>"
        f"<div class='l'>{escape(label)}</div></div>"
        for label, n in tiles
    )
    jump = "".join(
        f"<button type='button' class='jumpbtn' data-room='{room.room_id}' "
        f"style='--room:var(--acc-{room.accent})'><span class='jn'>{index:02d}</span>"
        f"<span class='jm'>{escape(room.name)}</span>"
        f"<span class='js'>{state['rooms'][room.room_id]['working']} of "
        f"{state['rooms'][room.room_id]['staff']} working</span></button>"
        for index, room in enumerate(ROOMS, start=1)
        if room.room_id != CONTROL
    )
    todo = (
        f"<p class='plain'><b>What to do:</b> {escape(health['todo'])}</p>"
        if health["todo"]
        else ""
    )
    return (
        f"<div class='health {escape(health['state'])}'><p class='headline'>"
        f"{escape(health['headline'])}</p><p>{escape(health['detail'])}</p>{todo}</div>"
        f"<p class='plain'>{escape(room_named(CONTROL).plain)}</p>"
        f"<div class='tiles'>{tile_html}</div>"
        f"<p class='faint'>{escape(state['wake'])}</p>"
        f"<h2>every room</h2><div class='jump'>{jump}</div>"
    )


def room_panel(session: Session, room_id: str, now: dt.datetime, provider: str = "") -> str | None:
    """The dashboard a room opens: tabs of real information about its work.

    The Control Room opens on the Manager: the operator's one portal (M63)."""
    from aurelis.manager.portal import manager_ref

    try:
        room = room_named(room_id)
    except KeyError:
        return None
    state = live_state(session, now)
    if room.room_id == CONTROL:
        boss = manager_ref(session)
        portal = (
            [
                (
                    "manager",
                    "talk to the Manager",
                    _talk(session, boss, MANAGER_HANDLE, provider, manager=True),
                )
            ]
            if boss is not None
            else []
        )
        tabs = [
            *portal,
            ("directives", "directives", directives_panel(session)),
            ("together", "working together", together_panel(session)),
            ("company", "the company", _control(session, state, now)),
            ("money", "path to real money", _lazy("mandate")),
            ("feed", "live feed", _now(state, CONTROL)),
            ("crew", "who works here", _crew(session, CONTROL, state)),
        ]
    else:
        from aurelis.station import pages

        assert room.department is not None
        extra, extra_label = _EXTRA[room.room_id]
        tabs = [
            ("brief", "the brief", _brief(room)),
            ("crew", "who works here", _crew(session, room.room_id, state)),
            ("now", "right now", _now(state, room.room_id)),
            (extra, extra_label, _lazy(extra)),
            ("details", "staff & charters", pages.department_page(session, room.department)),
        ]
    buttons = "".join(
        f"<button type='button' class='tabbtn{' on' if i == 0 else ''}' data-tab='{key}'>"
        f"{escape(label)}</button>"
        for i, (key, label, _) in enumerate(tabs)
    )
    sections = "".join(_section(key, body, hidden=i > 0) for i, (key, _, body) in enumerate(tabs))
    return f"<nav class='tabs'>{buttons}</nav>{sections}"


def _bold(escaped: str) -> str:
    """``**this**`` as bold, on text that is already escaped, and nothing else."""
    import re

    return re.sub(r"\*\*([^*\n]{1,200})\*\*", r"<b>\1</b>", escaped)


def _bubble(
    speaker: str, text: str, at: str, unsourced: list[str], handle: str, model: str | None = None
) -> str:
    who = "you" if speaker == "operator" else handle
    if model:
        at = f"{at} · {model}"
    flagged = (
        f"<span class='flag'>figures not from its material: {escape(', '.join(unsourced))}</span>"
        if unsourced
        else ""
    )
    return (
        f"<div class='bubble {escape(speaker)}'><span class='said'>{escape(who)} · {escape(at)}"
        f"</span><p>{_bold(escape(text))}</p>{flagged}</div>"
    )


def _provider_line(provider: str) -> str:
    if not provider:
        return ""
    if provider == "mock":
        return (
            "<p class='flagline'>Answers here come from the offline stand-in (mock), not a "
            "real model. Start the station with AURELIS_PROVIDER=agent_sdk to talk to the "
            "real agent.</p>"
        )
    return f"<p class='faint'>Answers come from {escape(provider)}.</p>"


MANAGER_ENDPOINT = "/office/manager"


def _talk(session: Session, ref: str, handle: str, provider: str, *, manager: bool) -> str:
    """The conversation box: what was said, and a place to say more."""
    from aurelis.chat.talk import thread

    log = "".join(
        _bubble(
            t.speaker,
            t.text,
            t.said_at.strftime("%m-%d %H:%M"),
            list(t.unsourced or []),
            handle,
            t.model,
        )
        for t in thread(session, ref)
    ) or (
        (
            "<p class='plain sm empty'>This is the Company Manager, your one portal into "
            "the company. Tell it what you want the company to do, focus on or stop doing; "
            "ask it what is going on, or what any agent thinks. It writes your instructions "
            "down as directives every agent reads, asks colleagues for you, and reports "
            "back.</p>"
        )
        if manager
        else (
            f"<p class='plain sm empty'>You have not talked to {escape(handle)} yet. Ask it "
            "anything: what it is working on, why it declined a market, what it thinks of "
            "its own record.</p>"
        )
    )
    endpoint = f" data-endpoint='{MANAGER_ENDPOINT}'" if manager else ""
    about = (
        "It answers from the whole company's situation. It can write a directive every "
        "agent reads, withdraw one, and ask up to three colleagues before it reports back; "
        "it cannot trade, grant data, override Risk or turn on real money. A message that "
        "makes it ask colleagues takes a few model calls and a few minutes."
        if manager
        else "It answers from its own seat, as itself: its charters, its method, its record "
        "and the shared brain. It can explain, argue and suggest; it cannot trade or change "
        "anything from here. Every line is kept on the record, and each answer is one model "
        "call on your subscription."
    )
    return (
        f"<div class='chat' data-chat='{escape(ref)}' data-handle='{escape(handle)}'{endpoint}>"
        f"<div class='chat-log'>{log}</div>"
        "<form class='chat-form'>"
        f"<textarea rows='2' placeholder='Say something to {escape(handle)}… "
        "(Enter to send, Shift+Enter for a new line)'></textarea>"
        "<button type='submit'>Send</button></form>"
        + _provider_line(provider)
        + f"<p class='faint'>{about}</p></div>"
    )


def lab_panel(session: Session) -> str:
    """The strategy lab's latest run, in plain words, then the numbers (M65)."""
    from aurelis.lab.run import lab_summary
    from aurelis.lab.tables import LabResult

    summary = lab_summary(session)
    if summary is None:
        return (
            "<p class='plain sm'>The strategy lab has not run yet. It runs once a week from "
            "the service, or now with <span class='mono'>aurelis lab run</span>.</p>"
        )
    families = "".join(
        f"<tr><td>{escape(name)}</td><td>{tests}</td><td>{survived}</td>"
        f"<td>{summary.family_oos.get(name, (0.0, 0.0))[0]}</td>"
        f"<td>{summary.family_oos.get(name, (0.0, 0.0))[1]}%</td></tr>"
        for name, (tests, survived) in sorted(
            summary.by_family.items(), key=lambda kv: -summary.family_oos.get(kv[0], (0.0, 0.0))[0]
        )
    )
    desks = "".join(
        f"<tr><td>{escape(desk)}</td><td>{tests}</td><td>{survived}</td></tr>"
        for desk, (tests, survived) in sorted(summary.by_desk.items())
    )
    top = list(
        session.execute(
            sa.select(LabResult)
            .where(LabResult.run_ref == summary.ref)
            .order_by(LabResult.oos_sharpe.desc())
            .limit(15)
        ).scalars()
    )
    best = "".join(
        f"<tr><td>{escape(r.strategy)}</td><td>{escape(r.symbol)}</td><td>{r.is_sharpe}</td>"
        f"<td>{r.oos_sharpe}</td><td>{r.oos_return}</td><td>{r.oos_hold}</td>"
        f"<td>{escape(r.verdict)}</td></tr>"
        for r in top
    )
    return (
        "<p class='plain'>The lab takes the strategies people teach (moving averages, "
        "momentum, breakouts, RSI and Bollinger reversion, MACD, and mechanical versions of "
        "the ICT fair value gap and the SMC liquidity sweep) and tests every one on years of "
        "daily history on every desk, after each desk's real costs. To <b>survive</b> a "
        "strategy must beat what luck alone would produce from this many tries in the first "
        "70% of the data, then beat simply holding the market in the last 30%, which it "
        "never saw.</p>"
        f"<div class='tiles'><div class='tile'><div class='n'>{summary.tests}</div>"
        "<div class='l'>tests</div></div>"
        f"<div class='tile'><div class='n'>{summary.markets}</div>"
        "<div class='l'>markets</div></div>"
        f"<div class='tile'><div class='n'>{summary.survivors}</div>"
        "<div class='l'>survived</div></div></div>"
        f"<p class='plain sm'>{escape(summary.line())}</p>"
        "<h2>by family, averaged over every market</h2><table><thead><tr><th>family</th>"
        "<th>tests</th><th>survived</th><th>mean out-of-sample Sharpe</th>"
        f"<th>beat holding</th></tr></thead><tbody>{families}</tbody></table>"
        "<h2>by desk</h2><table><thead><tr><th>desk</th><th>tests</th><th>survived</th></tr>"
        f"</thead><tbody>{desks}</tbody></table>"
        "<h2>best out of sample</h2><p class='plain sm'>Sorted by the last 30% alone, which "
        "is how people fool themselves: read the verdict column, not the order.</p>"
        "<table><thead><tr><th>strategy</th><th>market</th><th>in-sample Sharpe</th>"
        "<th>out-of-sample Sharpe</th><th>out-of-sample return</th><th>holding</th>"
        f"<th>verdict</th></tr></thead><tbody>{best}</tbody></table>"
    )


def together_panel(session: Session) -> str:
    """Who asked whom for help, the huddles held, and whether talking helps (M64)."""
    from aurelis.collab.huddle import HUDDLE, huddle_record
    from aurelis.meetings.tables import Decision, Meeting
    from aurelis.platform.db.tables import Event

    names = {p.ref: p.handle for p in people(session)}
    record = huddle_record(session)
    measured = (
        f"Brier before talking {record.brier_before}, after {record.brier_after}, over "
        f"{record.resolved} resolved view(s): {record.verdict()}."
        if record.brier_before is not None
        else f"{record.held} huddle(s) held; none of their views has resolved yet."
    )
    huddles = session.execute(
        sa.select(Meeting, Decision)
        .join(Decision, Decision.meeting_ref == Meeting.ref, isouter=True)
        .where(Meeting.type == HUDDLE)
        .order_by(Meeting.convened_at.desc())
        .limit(12)
    ).all()
    rows = "".join(
        f"<li><a href='/meeting/{escape(m.ref)}'>{escape(m.ref)}</a> "
        f"{m.convened_at:%m-%d %H:%M} · {escape(m.subject)} · position: "
        f"<b>{escape(d.outcome if d is not None else 'open')}</b>"
        + (
            " · after talking: "
            + ", ".join(
                f"{escape(names.get(e.get('agent', ''), e.get('agent', '')))} "
                f"{escape(str(e.get('before_up', ''))[:4])}→{escape(str(e.get('after_up')))}"
                for e in (d.supporting or [])
            )
            if d is not None
            else ""
        )
        + "</li>"
        for m, d in huddles
    )
    asked = session.execute(
        sa.select(Event.actor, Event.subject, Event.payload, Event.created_at)
        .where(Event.kind == "agent.consulted")
        .order_by(Event.seq.desc())
        .limit(15)
    ).all()
    asks = "".join(
        f"<li><span class='mono'>{at:%m-%d %H:%M}</span> <b>{escape(names.get(a, a))}</b> asked "
        f"<b>{escape(names.get(s or '', s or ''))}</b>: {escape(str(p.get('question', ''))[:160])}"
        f"<br><span class='faint'>answer: {escape(str(p.get('answer', ''))[:240])}</span></li>"
        for a, s, p, at in asked
    )
    return (
        "<p class='plain sm'>The agents work together in two ways. Before stating a view, any "
        "agent may ask one colleague one question; the question and the answer are real "
        "messages. And when two agents hold opposite open views on the same market, the "
        "company holds a huddle: each makes its case, answers the other and revises, and a "
        "moderator who holds neither view writes the company's position.</p>"
        f"<h2>does talking help?</h2><p class='plain sm'>{escape(measured)}</p>"
        + (
            f"<h2>huddles</h2><ul class='steps'>{rows}</ul>"
            if rows
            else "<p class='plain sm'>No huddle yet: no two agents have held opposite open "
            "views on one market since this was built.</p>"
        )
        + (
            f"<h2>who asked whom</h2><ul class='steps'>{asks}</ul>"
            if asks
            else "<p class='plain sm'>Nobody has asked a colleague for help yet.</p>"
        )
    )


def directives_panel(session: Session) -> str:
    """What the agents have been told, and what was withdrawn."""
    from aurelis.manager.directives import active
    from aurelis.manager.tables import Directive

    now_on = active(session)
    live = "".join(
        f"<li><b class='mono'>{escape(d.ref)}</b> for {escape(d.for_whom())}, since "
        f"{d.issued_at:%m-%d %H:%M}: {escape(d.text)}</li>"
        for d in now_on
    )
    withdrawn = list(
        session.execute(
            sa.select(Directive)
            .where(Directive.kind == "revoke")
            .order_by(Directive.issued_at.desc())
            .limit(20)
        ).scalars()
    )
    gone = "".join(
        f"<li><b class='mono'>{escape(str(r.revokes))}</b> withdrawn {r.issued_at:%m-%d %H:%M}</li>"
        for r in withdrawn
    )
    return (
        "<p class='plain sm'>Directives are your instructions, written down by the Manager. "
        "Every agent reads the active ones at every seat. To change one, tell the "
        "Manager.</p>"
        + (
            f"<h2>active</h2><ul class='steps'>{live}</ul>"
            if live
            else "<p class='plain sm'>No directive is active: the agents choose for themselves.</p>"
        )
        + (f"<h2>withdrawn</h2><ul class='steps'>{gone}</ul>" if gone else "")
    )


def agent_panel(session: Session, ref: str, provider: str = "") -> str | None:
    """One agent, opened over the map: a conversation with it, and its profile (M62).

    The Company Manager opens on the operator's portal (M63) rather than on an
    ordinary conversation."""
    from aurelis.station import pages

    profile = pages.agent_page(session, ref)
    if profile is None:
        return None
    handle = next((p.handle for p in people(session) if p.ref == ref), ref)
    talk = _talk(session, ref, handle, provider, manager=handle == MANAGER_HANDLE)
    return (
        "<nav class='tabs'><button type='button' class='tabbtn on' data-tab='talk'>talk</button>"
        "<button type='button' class='tabbtn' data-tab='profile'>profile</button></nav>"
        f"{_section('talk', talk, hidden=False)}{_section('profile', profile)}"
    )
