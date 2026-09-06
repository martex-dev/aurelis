"""One function per view. Each returns a page body; the shell adds the frame.

The drill-down is the product. Every path terminates in something citable — an
artifact digest, a registration hash, a ledger sequence number — and every
number on the way is a :class:`~aurelis.station.figures.Figure` carrying the
query it came from in its hover text.

The experiment page is the one that matters most. `CLAUDE.md` §24 asks that a
reader be able to answer *"why does the company believe this?"* by scrolling,
so that page puts the claim, the preregistration hash and its lock time, the
exact spec, the code version, the data fingerprint, the seed, every metric with
its source artifact, the objections and their discriminating tests, and the
derived verdict with the rule that derived it — in that order, on one page,
with nothing summarised away.
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent
from aurelis.meetings.tables import Meeting
from aurelis.missions.tables import Mission
from aurelis.org.departments import DEPARTMENTS, Department
from aurelis.org.desks import DESKS, Desk
from aurelis.research.tables import Hypothesis
from aurelis.station import projections as proj
from aurelis.station.layout import Facility
from aurelis.station.render import facility_svg, figure_span
from aurelis.station.svg import escape_text

__all__ = [
    "agent_page",
    "agents_page",
    "department_page",
    "desk_page",
    "facility_page",
    "floor_page",
    "graveyard_page",
    "hypothesis_page",
    "knowledge_page",
    "meeting_page",
    "meetings_page",
    "mission_page",
    "missions_page",
    "not_found",
    "research_page",
    "sealed_room_page",
    "timeline_page",
]

_STATE_TONE = {
    "confirmed": "ok",
    "refuted": "bad",
    "inconclusive": "warn",
    "underpowered": "warn",
    "shelved": "dim",
    "upheld": "bad",
    "rejected": "ok",
    "open": "warn",
    "untestable": "warn",
    "active": "ok",
    "working": "ok",
    "in_meeting": "warn",
    "closed": "dim",
    "succeeded": "ok",
    "failed": "bad",
}


def _pill(value: str) -> str:
    """A state word, upper-cased in the markup rather than by CSS.

    ``text-transform`` would make the page read ``REFUTED`` while the source
    said ``refuted``, so extracted text — a sealed snapshot's, a test's, a
    screen reader's — would disagree with what a reader saw. The transform is
    cosmetic; the letters are the record.
    """
    tone = _STATE_TONE.get(str(value).lower(), "dim")
    return f"<span class='pill {tone}'>{escape_text(str(value).upper())}</span>"


def _rows(headers: list[str], rows: list[list[str]]) -> str:
    """A table. Headers are upper-cased in the markup, for the reason in
    :func:`_pill`: extracted text must say what a reader saw."""
    if not rows:
        return "<p class='nodata'>Nothing recorded.</p>"
    head = "".join(f"<th>{escape_text(h.upper())}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _kv(pairs: list[tuple[str, str]]) -> str:
    cells = "".join(
        f"<div class='stat'><span class='k'>{escape_text(k.upper())}</span>"
        f"<span class='v'>{v}</span></div>"
        for k, v in pairs
    )
    return f"<div class='stats'>{cells}</div>"


def _when(moment: dt.datetime | None) -> str:
    return moment.strftime("%Y-%m-%d %H:%M") if moment else "—"


# ------------------------------------------------------------------ views


def facility_page(session: Session, facility: Facility) -> str:
    """The building. Rooms laid out from the registry, lit by the record."""
    statuses = proj.room_statuses(session)
    svg = facility_svg(facility, statuses)

    unstaffed = [s for s in statuses.values() if s.plate == "UNSTAFFED"]
    note = ""
    if unstaffed:
        names = ", ".join(DEPARTMENTS[s.department].name for s in unstaffed)
        note = (
            f"<div class='banner'>{len(unstaffed)} department(s) have no staff: "
            f"{escape_text(names)}. They are drawn at full size because a company "
            "that hides its empty rooms is describing an org chart, not an "
            "organisation.</div>"
        )
    return (
        "<h1>The facility</h1>"
        "<p class='mono'>Rooms are generated from the department registry and "
        "fixtures are placed by a hash of each room's id, so two builds of the "
        "same state produce the same picture. The Registry and the Vault have "
        "no corridor: you cannot walk into a process boundary.</p>"
        f"{note}<div class='panel'>{svg}</div>"
    )


def department_page(session: Session, department: Department) -> str:
    view = proj.department_view(session, department)
    agents = _rows(
        ["ref", "handle", "state", "seniority", "desk", "tier"],
        [
            [
                f"<a href='/agent/{escape_text(a['ref'])}'>{escape_text(a['ref'])}</a>",
                escape_text(a["handle"]),
                _pill(a["state"]),
                escape_text(a["seniority"]),
                escape_text(a["desk"]),
                escape_text(a["tier"]),
            ]
            for a in view.agents
        ],
    )
    charters = _rows(
        ["charter", "role"],
        [
            [f"<span class='mono'>{escape_text(c['id'])}</span>", escape_text(c["title"])]
            for c in view.charters
        ],
    )
    return (
        f"<h1>{escape_text(view.name)}</h1>"
        f"<p>{escape_text(view.owns)}</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("status", _pill(view.status.plate)),
                ("staff", figure_span(view.status.headcount)),
                ("busy", figure_span(view.status.working)),
                ("meetings", figure_span(view.meetings)),
                ("spend", figure_span(view.spend)),
                ("head charter", f"<span class='mono'>{escape_text(view.head_charter)}</span>"),
            ]
        )
        + "</div>"
        f"<h2>Staff</h2>{agents}"
        f"<h2>Charters held here</h2>{charters}"
    )


def agents_page(session: Session) -> str:
    rows = list(session.execute(sa.select(Agent).order_by(Agent.ref)).scalars())
    table = _rows(
        ["ref", "handle", "department", "desk", "state", "seniority"],
        [
            [
                f"<a href='/agent/{escape_text(row.ref)}'>{escape_text(row.ref)}</a>",
                escape_text(row.handle),
                escape_text(row.department),
                escape_text(row.desk or "—"),
                _pill(row.state),
                escape_text(row.seniority),
            ]
            for row in rows
        ],
    )
    return f"<h1>Staff</h1><p class='mono'>{len(rows)} hired.</p>{table}"


def agent_page(session: Session, ref: str) -> str | None:
    view = proj.agent_view(session, ref)
    if view is None:
        return None

    charters = "".join(
        f"<li><span class='mono'>{escape_text(c['id'])}</span> — "
        f"{escape_text(c['title'])}</li>"
        for c in view.charters
    )
    return (
        f"<h1>{escape_text(view.ref)} · {escape_text(view.handle)}</h1>"
        f"<p>{escape_text(view.department)} · desk {escape_text(view.desk)} · "
        f"{escape_text(view.seniority)} · tier {escape_text(view.tier)} · "
        f"{_pill(view.state)}</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("tool calls", figure_span(view.tool_calls)),
                ("refused", figure_span(view.refusals)),
                ("findings", figure_span(view.findings)),
                ("objections", figure_span(view.objections)),
                ("brier", figure_span(view.brier)),
                ("scored", figure_span(view.scored)),
                ("spend", figure_span(view.spend)),
                ("model calls", figure_span(view.model_calls)),
                ("cached", figure_span(view.cache_rate)),
            ]
        )
        + "</div>"
        "<h2>Training record</h2>"
        "<div class='panel'>"
        + _kv(
            [
                ("scenario verdict", _pill(view.scenario_verdict)),
                ("catch rate", figure_span(view.scenario_catch_rate)),
                ("false alarms", figure_span(view.scenario_false_alarms)),
                (
                    "specialty",
                    escape_text(", ".join(view.scenario_specialty)) or "none",
                ),
            ]
        )
        + "</div>"
        "<p class='mono'>Institutional competence on planted effects, not "
        "market truth. An agent calibrated on planted defects may still be "
        "miscalibrated on a real market, and this number is never merged with "
        "the live record above it.</p>"
        f"<h2>Charters held ({len(view.charters)})</h2><ul>{charters}</ul>"
        "<h2>Can see</h2>"
        f"<p class='mono'>{escape_text(', '.join(view.can_see)) or 'nothing'}</p>"
        "<h2>Can write</h2>"
        f"<p class='mono'>{escape_text(', '.join(view.can_write)) or 'nothing'}</p>"
        "<h2>Tools</h2>"
        f"<p class='mono'>{escape_text(', '.join(view.tools)) or 'none'}</p>"
        "<p class='mono'>Permissions are resolved from the charters above, not "
        "stored on the agent. Inspecting them is a click, which is what makes "
        "separation of duties legible rather than theoretical.</p>"
        f"<h2>Career</h2><p>hired {_when(view.hired_at)}"
        + (f" — {escape_text(view.note)}" if view.note else "")
        + "</p>"
    )


def missions_page(session: Session) -> str:
    rows = list(session.execute(sa.select(Mission).order_by(Mission.ref)).scalars())
    table = _rows(
        ["ref", "objective", "state", "opened"],
        [
            [
                f"<a href='/mission/{escape_text(row.ref)}'>{escape_text(row.ref)}</a>",
                escape_text(row.objective[:140]),
                _pill(row.state),
                _when(row.opened_at),
            ]
            for row in rows
        ],
    )
    return f"<h1>Missions</h1>{table}"


def mission_page(session: Session, ref: str) -> str | None:
    view = proj.mission_view(session, ref)
    if view is None:
        return None
    projects = _rows(
        ["ref", "intent", "state"],
        [
            [escape_text(p["ref"]), escape_text(p["intent"]), _pill(p["state"])]
            for p in view.projects
        ],
    )
    meetings = _rows(
        ["ref", "type", "subject"],
        [
            [
                f"<a href='/meeting/{escape_text(m['ref'])}'>{escape_text(m['ref'])}</a>",
                escape_text(m["type"]),
                escape_text(m["subject"]),
            ]
            for m in view.meetings
        ],
    )
    return (
        f"<h1>{escape_text(view.ref)}</h1><p>{escape_text(view.objective)}</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("state", _pill(view.state)),
                ("desks", escape_text(view.desk)),
                ("tasks", figure_span(view.tasks_total)),
                ("succeeded", figure_span(view.tasks_done)),
                ("spend", figure_span(view.spend)),
            ]
        )
        + "</div>"
        f"<h2>Projects</h2>{projects}"
        f"<h2>Meetings</h2>{meetings}"
    )


def meetings_page(session: Session) -> str:
    rows = list(
        session.execute(sa.select(Meeting).order_by(Meeting.convened_at.desc())).scalars()
    )
    table = _rows(
        ["ref", "type", "subject", "status", "productive", "cost"],
        [
            [
                f"<a href='/meeting/{escape_text(row.ref)}'>{escape_text(row.ref)}</a>",
                escape_text(row.type),
                escape_text(row.subject[:110]),
                _pill(row.status),
                "yes" if row.productive else "<span class='nodata'>no</span>",
                f"${row.usd_spent}",
            ]
            for row in rows
        ],
    )
    return (
        "<h1>Meetings</h1>"
        "<p class='mono'>A meeting is productive when it changed state. The "
        "column is recorded, not inferred at read time.</p>" + table
    )


def meeting_page(session: Session, ref: str) -> str | None:
    view = proj.meeting_view(session, ref)
    if view is None:
        return None

    turns = "".join(
        f"<div class='turn {escape_text(turn['stance'])}'>"
        f"<div class='who'>#{turn['seq']} · {escape_text(turn['phase'])} · "
        f"<a href='/agent/{escape_text(turn['speaker'])}'>"
        f"{escape_text(turn['speaker'])}</a> · {escape_text(turn['kind'])} · "
        f"stance {escape_text(turn['stance'])}"
        + (
            f" · <b>changed from {escape_text(turn['changed_mind_from'])}</b>"
            if turn["changed_mind_from"]
            else ""
        )
        + "</div>"
        f"<div>{escape_text(turn['body'])}</div>"
        + (
            f"<div class='mono'>cites {escape_text(', '.join(turn['evidence_refs']))}</div>"
            if turn["evidence_refs"]
            else ""
        )
        + "</div>"
        for turn in view.turns
    ) or "<p class='nodata'>No turns recorded.</p>"

    objections = _rows(
        ["ref", "author", "type", "severity", "status", "statement", "measured"],
        [
            [
                escape_text(o["ref"]),
                escape_text(o["author"]),
                escape_text(o["type"]),
                _pill(o["severity"]),
                _pill(o["status"]),
                escape_text(o["statement"]),
                f"<span class='mono'>{escape_text(str(o['result'].get('detail', '')))}</span>",
            ]
            for o in view.objections
        ],
    )
    decisions = "".join(
        f"<div class='panel'><b>{escape_text(d['ref'])}</b> — "
        f"{escape_text(d['outcome'])}"
        f"<div class='mono'>{escape_text(d['rationale'])}</div>"
        f"<div>supporting: {escape_text(', '.join(map(str, d['supporting']))) or '—'}</div>"
        f"<div>dissent: {escape_text(str(d['dissent'])) if d['dissent'] else 'none recorded'}</div>"
        "</div>"
        for d in view.decisions
    ) or "<p class='nodata'>No decision recorded.</p>"

    forecasts = _rows(
        ["agent", "probability", "outcome", "brier"],
        [
            [
                escape_text(f["agent_ref"]),
                escape_text(str(f["probability"])),
                "—" if f["outcome"] is None else str(f["outcome"]),
                "—" if f["brier"] is None else str(f["brier"]),
            ]
            for f in view.forecasts
        ],
    )

    return (
        f"<h1>{escape_text(view.ref)} · {escape_text(view.type)}</h1>"
        f"<p>{escape_text(view.subject)}</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("status", _pill(view.status)),
                ("chair", escape_text(view.chair)),
                ("productive", "yes" if view.productive else "no"),
                ("rounds", figure_span(view.rounds)),
                ("tokens", figure_span(view.tokens)),
                ("cost", figure_span(view.usd)),
            ]
        )
        + (
            f"<div class='mono'>evidence pack {escape_text(view.evidence_digest or '—')}</div>"
        )
        + "</div>"
        f"<h2>Forecasts, made before the argument</h2>{forecasts}"
        f"<h2>Transcript</h2>{turns}"
        f"<h2>Objections</h2>{objections}"
        f"<h2>Decision and dissent</h2>{decisions}"
    )


def research_page(session: Session) -> str:
    rows = list(session.execute(sa.select(Hypothesis).order_by(Hypothesis.ref)).scalars())
    table = _rows(
        ["ref", "claim", "state", "family", "desk", "author"],
        [
            [
                f"<a href='/hypothesis/{escape_text(row.ref)}'>{escape_text(row.ref)}</a>",
                escape_text(row.claim[:120]),
                _pill(row.state),
                escape_text(row.family),
                escape_text(row.desk or "—"),
                escape_text(row.author),
            ]
            for row in rows
        ],
    )
    return f"<h1>Research</h1>{table}"


def hypothesis_page(session: Session, ref: str) -> str | None:
    """Why does the company believe this? Answered by scrolling."""
    view = proj.hypothesis_view(session, ref)
    if view is None:
        return None

    registration = view.registration
    if registration is None:
        prereg = (
            "<p class='nodata'>No registration. Nothing may run for this "
            "hypothesis until one is locked.</p>"
        )
    else:
        prereg = (
            "<div class='panel'>"
            + _kv(
                [
                    ("ref", escape_text(registration["ref"])),
                    ("kind", _pill(registration["kind"])),
                    ("locked", _when(registration["locked_at"])),
                    ("by", escape_text(registration["locked_by"] or "—")),
                    ("declared cells", str(registration["declared_cells"])),
                    ("seed", str(registration["seed"])),
                ]
            )
            + f"<div class='mono'>spec digest {escape_text(registration['digest'])}</div>"
            + f"<div>{escape_text(registration['analysis_plan'])}</div>"
            + "<div class='mono'>criteria committed before the run: "
            + escape_text(str(registration["pass_criteria"]))
            + "</div></div>"
        )

    runs = _rows(
        ["run", "status", "engine", "code", "data fingerprint", "seed", "artifact"],
        [
            [
                escape_text(run["ref"]),
                _pill(run["status"]),
                escape_text(run["engine"]),
                f"<span class='mono'>{escape_text(run['code_version'])}</span>",
                f"<span class='mono'>{escape_text(run['data_fingerprint'])}</span>",
                str(run["seed"]),
                f"<span class='mono'>{escape_text(run['artifact_digest'] or '—')}</span>",
            ]
            for run in view.runs
        ],
    )
    results = _rows(
        ["metric", "value", "interval", "split", "computed by", "method"],
        [
            [
                escape_text(r["metric"]),
                figure_span(r["value"]),
                (
                    f"[{r['low']}, {r['high']}]"
                    if r["low"] is not None
                    else "<span class='nodata'>no interval</span>"
                ),
                escape_text(r["split"]),
                _pill(r["computed_by"]),
                f"<span class='mono'>{escape_text(r['method'])}</span>",
            ]
            for r in view.results
        ],
    )
    findings = "".join(
        f"<div class='panel'><b>{escape_text(f['ref'])}</b> {_pill(f['verdict'])}"
        f"<div>{escape_text(f['statement'])}</div>"
        f"<div class='mono'>{escape_text(f['verdict_reason'])}</div>"
        + (
            f"<div class='mono'>confidence capped: {escape_text(f['cap_reason'])}</div>"
            if f["cap_reason"]
            else ""
        )
        + f"<div class='mono'>checks: {escape_text(str(f['verdict_checks']))}</div>"
        "</div>"
        for f in view.findings
    ) or "<p class='nodata'>No finding written.</p>"

    objections = _rows(
        ["ref", "type", "severity", "status", "statement", "measured"],
        [
            [
                escape_text(o["ref"]),
                escape_text(o["type"]),
                _pill(o["severity"]),
                _pill(o["status"]),
                escape_text(o["statement"]),
                f"<span class='mono'>{escape_text(str(o['result'].get('detail', '')))}</span>",
            ]
            for o in view.objections
        ],
    )
    evidence = _rows(
        ["kind", "polarity", "statement", "artifact"],
        [
            [
                _pill(e["kind"]),
                escape_text(e["polarity"]),
                escape_text(e["statement"]),
                f"<span class='mono'>{escape_text(e['artifact_digest'] or '—')}</span>",
            ]
            for e in view.evidence
        ],
    )

    prior = (
        escape_text(", ".join(view.prior_art))
        if view.prior_art
        else "<span class='nodata'>none recorded at screening</span>"
    )

    return (
        f"<h1>{escape_text(view.ref)}</h1><p>{escape_text(view.claim)}</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("state", _pill(view.state)),
                ("family", escape_text(view.family)),
                ("desk", escape_text(view.desk)),
                ("author", escape_text(view.author)),
                ("primary metric", escape_text(view.primary_metric)),
                ("minimum effect", figure_span(view.minimum_effect)),
            ]
        )
        + (
            f"<div class='mono'>{escape_text(view.verdict_reason)}</div>"
            if view.verdict_reason
            else ""
        )
        + "</div>"
        f"<h2>Prior art, checked before spending</h2><p>{prior}</p>"
        f"<h2>Preregistration</h2>{prereg}"
        f"<h2>Runs — provenance</h2>{runs}"
        f"<h2>Measurements</h2>{results}"
        "<p class='mono'>No agent may write a row here: the "
        "<code>computed_by</code> column accepts only <code>engine</code> or "
        "<code>custodian</code>, and the database enforces it.</p>"
        f"<h2>Findings and the derived verdict</h2>{findings}"
        f"<h2>Evidence</h2>{evidence}"
        f"<h2>Objections</h2>{objections}"
    )


def desk_page(session: Session, desk: Desk) -> str:
    view = proj.desk_view(session, desk)
    return (
        f"<h1>{escape_text(view.name)} desk</h1>"
        "<div class='panel'>"
        + _kv(
            [
                ("status", _pill(view.status.value)),
                ("opens at", escape_text(view.opens_at or "—")),
                ("calendar", escape_text(view.calendar)),
                ("agents", figure_span(view.agents)),
                ("hypotheses", figure_span(view.hypotheses)),
                ("strategies", figure_span(view.strategies)),
            ]
        )
        + "</div>"
        f"<h2>Instruments</h2><p class='mono'>{escape_text(', '.join(view.instruments))}</p>"
        f"<h2>Engines</h2><p class='mono'>{escape_text(', '.join(view.engines))}</p>"
        + (f"<p>{escape_text(view.notes)}</p>" if view.notes else "")
    )


def floor_page(session: Session) -> str:
    rows = [
        [
            f"<a href='/desk/{desk.value}'>{escape_text(spec.name)}</a>",
            _pill(spec.status.value),
            escape_text(spec.opens_at_milestone or "—"),
            escape_text(", ".join(spec.instruments)),
            escape_text(spec.calendar),
        ]
        for desk, spec in DESKS.items()
    ]
    return (
        "<h1>The Floor</h1>"
        "<p class='mono'>Every desk in the registry, whatever its status. A "
        "desk scheduled for a later milestone is drawn as scheduled — showing "
        "only the open ones would make the company's reach look like its "
        "current footprint.</p>"
        + _rows(["desk", "status", "opens", "instruments", "calendar"], rows)
    )


def graveyard_page(session: Session) -> str:
    view = proj.graveyard_view(session)
    table = _rows(
        ["ref", "claim", "state", "family", "desk", "why it died"],
        [
            [
                f"<a href='/hypothesis/{escape_text(row['ref'])}'>{escape_text(row['ref'])}</a>",
                escape_text(row["claim"][:110]),
                _pill(row["state"]),
                escape_text(row["family"]),
                escape_text(row["desk"]),
                escape_text(row["reason"][:220]),
            ]
            for row in view.rows
        ],
    )
    return (
        "<h1>The Graveyard</h1>"
        "<p class='mono'>A full room, not a hidden tab. A researcher that "
        "correctly kills a bad idea has produced valuable work, and this is "
        "where the company keeps it.</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("refuted", figure_span(view.refuted)),
                ("inconclusive", figure_span(view.inconclusive)),
                ("underpowered", figure_span(view.underpowered)),
                ("shelved", figure_span(view.shelved)),
            ]
        )
        + "</div>"
        "<p class='mono'>INCONCLUSIVE is a statement about the world: there is "
        "an effect and it is smaller than claimed. UNDERPOWERED is a statement "
        "about the design: the interval is too wide to say either way. They are "
        "counted separately because collapsing them is how confident nothing "
        "accumulates.</p>" + table
    )


def knowledge_page(session: Session) -> str:
    view = proj.knowledge_view(session)
    corpora = "".join(
        "<div class='panel'>"
        f"<b>{escape_text(row['corpus'])}</b> "
        + (
            "<span class='pill ok'>RECONCILES</span>"
            if row["reconciles"]
            else "<span class='pill bad'>DOES NOT RECONCILE</span>"
        )
        + _kv(
            [
                ("claimed", figure_span(row["claimed"])),
                ("documented", figure_span(row["documented"])),
                ("unallocated", figure_span(row["unallocated"])),
            ]
        )
        + f"<div class='mono'>{escape_text(row['reason'])}</div>"
        + f"<div class='mono'>ledger digest {escape_text(row['digest'])}</div>"
        "</div>"
        for row in view.corpora
    ) or "<p class='nodata'>No corpus imported.</p>"

    lessons = _rows(
        ["ref", "lesson", "binding", "from"],
        [
            [
                escape_text(row["ref"]),
                escape_text(row["statement"]),
                "<span class='pill warn'>STANDING RULE</span>"
                if row["standing_rule"]
                else "—",
                escape_text(row["source_ref"] or "—"),
            ]
            for row in view.recent_lessons
        ],
    )
    return (
        "<h1>Knowledge &amp; Memory</h1>"
        "<div class='panel'>"
        + _kv(
            [
                ("inherited trials", figure_span(view.trials)),
                ("lessons", figure_span(view.lessons)),
                ("standing rules", figure_span(view.standing_rules)),
            ]
        )
        + "</div>"
        f"<h2>Inherited corpora</h2>{corpora}"
        "<p class='mono'>Figures are reproduced as published and never "
        "recomputed. Where an import's own totals do not add up, the gap is "
        "carried rather than distributed.</p>"
        f"<h2>Lessons</h2>{lessons}"
    )


def timeline_page(session: Session, limit: int = 200) -> str:
    entries = proj.timeline(session, limit=limit)
    items = "".join(
        "<li>"
        f"<span class='seq'>{entry.seq}</span>"
        f"<span>{entry.at.strftime('%m-%d %H:%M')}</span>"
        f"<span class='kind'>{escape_text(entry.kind)}</span>"
        "<span>"
        + (
            f"<a href='{escape_text(entry.href)}'>{escape_text(entry.subject)}</a>"
            if entry.href
            else escape_text(entry.subject)
        )
        + f" · {escape_text(entry.actor)}"
        + (f" · <span class='mono'>{escape_text(entry.summary)}</span>" if entry.summary else "")
        + "</span></li>"
        for entry in entries
    )
    return (
        "<h1>Company timeline</h1>"
        "<p class='mono'>A projection of the event table — ordered, actored, "
        "subjected. The ledger already holds all three, so this view invents "
        "nothing and costs one query.</p>"
        f"<ul class='timeline' id='timeline'>{items}</ul>"
    )


def sealed_room_page(room_id: str, title: str, owns: str) -> str:
    return (
        f"<h1>{escape_text(title)}</h1>"
        f"<p>{escape_text(owns)}</p>"
        "<div class='banner'>This room has no corridor. It is a process "
        "boundary, not a place, and drawing a door into it would be drawing a "
        "way around a rule.</div>"
        + (
            "<p>Preregistrations lock here. Once locked, a registration's spec, "
            "criteria, seed and kind cannot change — enforced by a database "
            "trigger, not by convention. A revised design is a new row, "
            "automatically degraded to exploratory.</p>"
            if room_id == "registry"
            else "<p>Sealed out-of-sample data lives here, released only by the "
            "Custodian against a counted budget. No agent holds a scope that "
            "reaches it.</p>"
        )
    )


def not_found(what: str) -> str:
    return (
        "<h1>Not found</h1>"
        f"<p class='nodata'>{escape_text(what)} is not in the record.</p>"
        "<p class='mono'>The station shows nothing rather than something "
        "plausible. That is rule one.</p>"
    )
