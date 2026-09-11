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
from typing import Any

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
    "service_page",
    "theses_page",
    "thesis_page",
    "timeline_page",
    "mechanism_page",
    "mechanisms_page",
    "world_page",
]

_STATE_TONE = {
    "stands": "ok",
    "weakened": "warn",
    "broken": "bad",
    "unreadable": "dim",
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
        "<h2>Forward record</h2>"
        "<div class='panel'>"
        + _kv(
            [
                ("views sealed", figure_span(view.views_sealed)),
                ("views scored", figure_span(view.views_scored)),
                ("right", figure_span(view.views_hit_rate)),
                ("brier", figure_span(view.views_brier)),
                ("base rate", figure_span(view.views_base_rate)),
                ("on fixtures", figure_span(view.views_fixture)),
            ]
        )
        + "</div>"
        + (
            _rows(
                ["band", "views", "said", "right", "over-confident by"],
                [
                    [
                        escape_text(b["band"]),
                        escape_text(b["n"]),
                        escape_text(b["stated"]),
                        escape_text(b["observed"]),
                        escape_text(b["gap"]),
                    ]
                    for b in view.views_bands
                ],
            )
            if view.views_bands
            else ""
        )
        + "<p class='mono'>Views sealed before the outcome existed and scored "
        "when the horizon expired. Brier: (p - outcome)^2, lower is better, 0.25 "
        "is always saying 50%. Market recordings only; views on fixtures are "
        "counted beside, never in. See <a href='/theses'>theses</a>.</p>"
        "<h2>As the adversary</h2>"
        "<div class='panel'>"
        + _kv(
            [
                ("views attacked", figure_span(view.attacks)),
                ("caught", figure_span(view.attacks_caught)),
                ("false alarms", figure_span(view.attacks_false_alarms)),
                ("missed", figure_span(view.attacks_missed)),
            ]
        )
        + "</div>"
        "<p class='mono'>A critic is scored on whether its verdicts predicted "
        "failure: a broken on a view that turned out wrong is a catch, on one that "
        "turned out right a false alarm, and a stands on a view that turned out "
        "wrong a miss. Say broken to everything and the false alarms say so.</p>"
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
                ("bars a year", figure_span(view.bars_per_year)),
                ("round trip", figure_span(view.round_trip_bps)),
                ("material size", figure_span(view.material_size_usd)),
                ("agents", figure_span(view.agents)),
                ("hypotheses", figure_span(view.hypotheses)),
                ("strategies", figure_span(view.strategies)),
            ]
        )
        + "</div>"
        f"<h2>Instruments</h2><p class='mono'>{escape_text(', '.join(view.instruments))}</p>"
        f"<h2>Engines</h2><p class='mono'>{escape_text(', '.join(view.engines))}</p>"
        + (
            "<h2>Data</h2>"
            + (
                "<p class='mono'>LIVE</p>"
                if view.data_is_live
                else "<p class='mono'>NOT LIVE — fixture data. Deterministic, "
                "offline, and not a market. No research conclusion about a "
                "real market may be drawn from anything on this page.</p>"
            )
            + (
                "<ul>"
                + "".join(f"<li>{escape_text(c)}</li>" for c in view.caveats)
                + "</ul>"
                if view.caveats
                else ""
            )
        )
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


def _fixture_tag(is_live: bool) -> str:
    return "" if is_live else " <span class='pill dim'>FIXTURE</span>"


def _thesis_row_open(row: dict[str, Any]) -> list[str]:
    left = "due" if row["due"] else f"{row['hours_left']}h left"
    return [
        f"<a href='/thesis/{escape_text(row['ref'])}'>{escape_text(row['ref'])}</a>",
        f"<a href='/agent/{escape_text(row['agent'])}'>{escape_text(row['agent'])}</a>",
        escape_text(row["instrument"]) + _fixture_tag(row["is_live"]),
        escape_text(f"{row['direction']} {row['horizon']}"),
        escape_text(row["confidence"]),
        escape_text(row["reference"]),
        _when(row["resolves_at"])
        + f" <span class='pill warn'>{escape_text(left).upper()}</span>",
    ]


def _thesis_row_scored(row: dict[str, Any]) -> list[str]:
    return [
        f"<a href='/thesis/{escape_text(row['ref'])}'>{escape_text(row['ref'])}</a>",
        f"<a href='/agent/{escape_text(row['agent'])}'>{escape_text(row['agent'])}</a>",
        escape_text(row["instrument"]) + _fixture_tag(row["is_live"]),
        escape_text(f"{row['direction']} {row['horizon']}"),
        escape_text(row["confidence"]),
        escape_text(f"{row['reference']} → {row['resolution']}"),
        "<span class='pill ok'>RIGHT</span>"
        if row["hit"]
        else "<span class='pill bad'>WRONG</span>",
        escape_text(row["brier"]),
    ]


def theses_page(session: Session, *, now: dt.datetime) -> str:
    view = proj.theses_view(session, now=now)
    open_table = _rows(
        ["ref", "agent", "market", "view", "confidence", "reference", "resolves"],
        [_thesis_row_open(r) for r in view.open_rows],
    )
    scored_table = _rows(
        ["ref", "agent", "market", "view", "confidence", "reference → close", "outcome", "brier"],
        [_thesis_row_scored(r) for r in view.scored_rows],
    )
    agents = _rows(
        ["agent", "sealed", "scored", "right", "brier", "base rate"],
        [
            [
                f"<a href='/agent/{escape_text(a.label)}'>{escape_text(a.label)}</a>",
                str(a.sealed),
                str(a.scored),
                str(a.hit_rate) if a.hit_rate is not None else "—",
                str(a.mean_brier) if a.mean_brier is not None else "—",
                str(a.base_rate_brier) if a.base_rate_brier is not None else "—",
            ]
            for a in view.by_agent
        ],
    )
    return (
        "<h1>Theses</h1>"
        "<p class='mono'>Views agents sealed before the outcome existed. Each "
        "one names a market, a horizon, a direction and a confidence, is hashed "
        "at sealing, and is scored once against a recording when the horizon "
        "expires. This is the forward record: it cannot be backtested into "
        "existence, and a wrong call stays on the page.</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("sealed on markets", figure_span(view.sealed)),
                ("scored", figure_span(view.scored)),
                ("right", figure_span(view.right)),
                ("brier", figure_span(view.brier)),
                ("base rate", figure_span(view.base_rate)),
                ("on fixtures", figure_span(view.fixture)),
            ]
        )
        + "</div>"
        f"<h2>Open ({len(view.open_rows)})</h2>{open_table}"
        f"<h2>Scored ({len(view.scored_rows)})</h2>{scored_table}"
        f"<h2>By agent</h2>{agents}"
        "<p class='mono'>Brier is (p - outcome)^2, lower is better; 0.25 is "
        "always saying 50%. The base rate is what always predicting the observed "
        "up-frequency would have scored: a record that beats the coin toss but "
        "not the base rate has learned the market's drift and nothing else.</p>"
    )


def thesis_page(session: Session, ref: str) -> str | None:
    from aurelis.judgement.seat import verify_seal
    from aurelis.judgement.tables import Thesis

    row = session.execute(sa.select(Thesis).where(Thesis.ref == ref)).scalar_one_or_none()
    if row is None:
        return None
    settled = row.scored_at is not None
    hit = bool(row.outcome) == (row.direction == "up") if settled else None
    pairs = [
        (
            "agent",
            f"<a href='/agent/{escape_text(row.agent_ref)}'>{escape_text(row.agent_ref)}</a>",
        ),
        ("market", escape_text(row.instrument) + _fixture_tag(row.is_live)),
        ("view", escape_text(f"{row.direction} over {row.horizon_hours}h")),
        ("confidence", escape_text(str(row.confidence))),
        ("probability up", escape_text(str(row.probability_up))),
        ("reference close", escape_text(row.reference_close)),
        ("reference bar", _when(row.reference_at)),
        ("resolves", _when(row.resolves_at)),
        ("sealed", _when(row.sealed_at)),
        ("recording shown", escape_text(row.snapshot_ref)),
        ("material", f"<span class='mono'>{escape_text(row.material_digest[:16])}</span>"),
        ("model", escape_text(row.model)),
        ("seal", f"<span class='mono'>{escape_text(row.seal[:16])}</span> "
                 + (
                     "<span class='pill ok'>VERIFIES</span>"
                     if verify_seal(row)
                     else "<span class='pill bad'>BROKEN</span>"
                 )),
    ]
    if row.critic_ref is not None:
        pairs += [
            (
                "attacked by",
                f"<a href='/agent/{escape_text(row.critic_ref)}'>{escape_text(row.critic_ref)}</a>",
            ),
            ("verdict", _pill(row.attack_verdict or "—")),
            ("attack", escape_text(row.attack or "")),
            ("confidence stated", escape_text(str(row.confidence_stated))),
            ("response", escape_text(f"{row.response}: {row.response_because or ''}")),
        ]
    else:
        pairs.append(("attacked by", "nobody — no critic was available"))
    if settled:
        pairs += [
            (
                "outcome",
                "<span class='pill ok'>RIGHT</span>"
                if hit
                else "<span class='pill bad'>WRONG</span>",
            ),
            ("close at horizon", escape_text(row.resolution_close or "—")),
            ("resolution bar", _when(row.resolution_at)),
            ("brier", escape_text(str(row.brier))),
            ("scored against", escape_text(row.scored_against or "—")),
            ("scored", _when(row.scored_at)),
        ]
    else:
        pairs.append(("outcome", "<span class='pill warn'>OPEN</span>"))
    return (
        f"<h1>{escape_text(row.ref)}</h1>"
        "<div class='panel'>" + _kv(pairs) + "</div>"
        f"<h2>Thesis</h2><p>{escape_text(row.thesis)}</p>"
        f"<h2>Wrong if</h2><p>{escape_text(row.wrong_if)}</p>"
        "<p class='mono'>Sealed fields cannot be edited and the row cannot be "
        "deleted; the database refuses. The score is written once, by the "
        "resolver, from the close of the bar that opened at the horizon.</p>"
    )


def service_page(session: Session) -> str:
    view = proj.service_view(session)
    grants = _rows(
        ["ref", "source", "desk", "instruments", "bars", "by", "why", "state"],
        [
            [
                escape_text(g["ref"]),
                escape_text(g["source"]),
                escape_text(g["desk"]),
                escape_text(g["instruments"]),
                str(g["bars"]),
                escape_text(g["by"]),
                escape_text(g["reason"][:120]),
                "<span class='pill ok'>ACTIVE</span>"
                if g["active"]
                else "<span class='pill dim'>REVOKED</span>",
            ]
            for g in view.grants
        ],
    )
    wakes = _rows(
        [
            "wake",
            "at",
            "fetched",
            "failed",
            "scored",
            "pending",
            "run",
            "calls",
            "left",
            "incidents",
            "note",
        ],
        [
            [
                escape_text(w["ref"]),
                _when(w["at"]),
                str(w["fetched"]),
                str(w["fetch_failures"]),
                str(w["scored"]),
                str(w["pending"]),
                escape_text(w["run"]),
                str(w["calls"]),
                str(w["left"]),
                str(w["incidents"]),
                escape_text(w["note"][:80]),
            ]
            for w in view.wakes
        ],
    )
    incidents = _rows(
        ["ref", "severity", "source", "at", "message", "state"],
        [
            [
                escape_text(i["ref"]),
                _pill(i["severity"]),
                escape_text(i["source"]),
                _when(i["at"]),
                escape_text(i["message"][:140]),
                "<span class='pill warn'>OPEN</span>"
                if i["open"]
                else "<span class='pill dim'>RESOLVED</span>",
            ]
            for i in view.incidents
        ],
    )
    return (
        "<h1>The Service</h1>"
        "<p class='mono'>The company running unattended: every wake fetches "
        "under a grant a person recorded, settles every view a recording "
        "covers, runs the loop inside a daily model-call budget, and writes "
        "down what happened. A vendor outage or a model out of allowance is an "
        "incident here, not a crash. It fetches nothing that is not granted and "
        "it cannot trade.</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("wakes", figure_span(view.wakes_total)),
                ("last wake", _when(view.last_wake_at)),
                ("open incidents", figure_span(view.open_incidents)),
            ]
        )
        + "</div>"
        f"<h2>Grants</h2>{grants}"
        f"<h2>Wakes</h2>{wakes}"
        f"<h2>Incidents</h2>{incidents}"
    )


def mechanisms_page(session: Session) -> str:
    view = proj.mechanisms_view(session)
    rows = _rows(
        [
            "ref",
            "title",
            "agent",
            "trigger",
            "predicts",
            "scored",
            "brier",
            "base rate",
            "paper trades",
            "paper P&L",
            "verdict",
        ],
        [
            [
                f"<a href='/mechanism/{escape_text(r['ref'])}'>{escape_text(r['ref'])}</a>",
                escape_text(r["title"][:40]),
                f"<a href='/agent/{escape_text(r['agent'])}'>{escape_text(r['agent'])}</a>",
                escape_text(f"{r['trigger']} {r['direction']} {r['horizon']}h"),
                str(r["predictions"]),
                str(r["scored"]),
                escape_text(r["brier"]),
                escape_text(r["base_rate"]),
                escape_text(f"{r['paper']['closed']} closed, {r['paper']['open']} open"),
                escape_text(str(r["paper"]["pnl"])),
                (
                    "<span class='pill ok'>SCHEME</span>"
                    if r["is_scheme"]
                    else "<span class='pill bad'>RETIRED</span>"
                    if r["retired"]
                    else f"<span class='pill warn'>{escape_text(r['verdict']).upper()}</span>"
                ),
            ]
            for r in view.rows
        ],
    )
    hunt = proj.hunt_view(session)
    declines = _rows(
        ["at", "agent", "shown", "because"],
        [
            [
                _when(d["at"]),
                f"<a href='/agent/{escape_text(d['agent'])}'>{escape_text(d['agent'])}</a>",
                escape_text(f"{d['trigger']} → {d['then']}"),
                escape_text(d["because"] or "no reason given") if d["because"]
                else "<span class='nodata'>no reason given</span>",
            ]
            for d in hunt.declines
        ],
    )
    return (
        "<h1>Mechanisms</h1>"
        "<p class='mono'>The join from a mined conjunction to a tested scheme. An "
        "agent states why a pattern should work, who is on the other side, and how "
        "it decays; the mechanism then predicts every other occurrence, sealed "
        "before the outcome and scored. The instance it was found on is excluded. "
        "A mechanism is a scheme only when its out-of-sample predictions beat a "
        "coin toss and the instrument's own drift; one that does not is retired and "
        "kept. A scheme trades its firings on paper through Risk; its P&L is "
        "reported and never judged, because over a short window it is mostly luck.</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("mechanisms", figure_span(view.total)),
                ("candidate schemes", figure_span(view.schemes)),
                ("retired", figure_span(view.retired)),
                ("declined", figure_span(hunt.declined_total)),
            ]
        )
        + "</div>"
        f"{rows}"
        "<h2>Declined, and why</h2>"
        "<p class='mono'>Agents shown a mined conjunction with its in-sample "
        "evidence who would not state a mechanism over it. A record of refusals "
        "with reasons is most of what the company knows about which patterns are "
        "coincidences.</p>"
        f"{declines}"
    )


def mechanism_page(session: Session, ref: str, *, artifacts: Any = None) -> str | None:
    """One mechanism, unfolded: the statement, what the agent was shown, every
    prediction with its outcome, the paper trades, and who declined the same
    trigger and why. The page draws the record; the verdict is the library's."""
    view = proj.mechanism_detail(session, ref, artifacts=artifacts)
    if view is None:
        return None
    verdict = (
        "<span class='pill ok'>SCHEME</span>"
        if view.is_scheme
        else "<span class='pill bad'>RETIRED</span>"
        if view.retired
        else f"<span class='pill warn'>{escape_text(view.verdict).upper()}</span>"
    )
    statement = _kv(
        [
            (
                "stated by",
                f"<a href='/agent/{escape_text(view.agent)}'>{escape_text(view.agent)}</a>",
            ),
            ("trigger", escape_text(view.trigger)),
            (
                "claims",
                escape_text(f"{view.direction} over {view.horizon}h at {view.confidence}"),
            ),
            ("found on", escape_text(view.found_on)),
            ("origin", escape_text(view.origin)),
            ("stated", _when(view.stated_at)),
            ("model", escape_text(view.model)),
            ("seal", f"<span class='mono'>{escape_text(view.seal[:16])}</span>"),
            ("verdict", verdict),
        ]
    )
    story = (
        f"<div class='turn'><span class='who'>WHY</span><br>{escape_text(view.why)}</div>"
        f"<div class='turn opposes'><span class='who'>OTHER SIDE</span><br>"
        f"{escape_text(view.other_side)}</div>"
        f"<div class='turn'><span class='who'>DECAY</span><br>{escape_text(view.decay)}</div>"
    )
    if view.retired:
        reason = escape_text(view.retired_reason or "no reason recorded")
        story += f"<div class='banner'>RETIRED — {reason}</div>"
    record = _kv(
        [
            ("predictions", str(view.predictions)),
            ("scored", str(view.scored)),
            ("right", str(view.hits)),
            ("brier", escape_text(view.brier)),
            ("base rate", escape_text(view.base_rate)),
        ]
    )
    shown = [[escape_text(k), escape_text(v)] for k, v in view.evidence]
    evidence = (
        _rows(["what the agent was shown", "figure"], shown)
        if view.evidence
        else "<p class='nodata'>No evidence artifact: stated before the miner showed its "
        "evidence, or by hand.</p>"
    )
    if view.evidence:
        evidence += (
            f"<p class='mono'>artifact {escape_text(view.evidence_digest[:16])} — in-sample "
            "figures are the reason the question was asked, not evidence it predicts; "
            "the predictions below are the test.</p>"
        )
    by_instrument = _rows(
        ["instrument", "predictions", "scored", "right"],
        [
            [escape_text(b["instrument"]), str(b["n"]), str(b["scored"]), str(b["hits"])]
            for b in view.by_instrument
        ],
    )
    predictions = _rows(
        ["ref", "instrument", "reference bar", "close", "resolves", "outcome", "brier"],
        [
            [
                f"<a href='/thesis/{escape_text(r['ref'])}'>{escape_text(r['ref'])}</a>",
                escape_text(r["instrument"]) + _fixture_tag(r["is_live"]),
                _when(r["reference_at"]),
                escape_text(r["reference_close"]),
                _when(r["resolves_at"]),
                _pill(r["state"]),
                escape_text(r["brier"] or "—"),
            ]
            for r in view.rows[:200]
        ],
    )
    trades = _rows(
        ["thesis", "portfolio", "opened", "closed", "P&L"],
        [
            [
                f"<a href='/thesis/{escape_text(t['thesis'])}'>{escape_text(t['thesis'])}</a>",
                escape_text(t["portfolio"]),
                _when(t["opened_at"]),
                _when(t["closed_at"]),
                escape_text(t["pnl"] or "open"),
            ]
            for t in view.trades
        ],
    )
    declines = _rows(
        ["at", "agent", "shown", "because"],
        [
            [
                _when(d["at"]),
                f"<a href='/agent/{escape_text(d['agent'])}'>{escape_text(d['agent'])}</a>",
                escape_text(f"{d['trigger']} → {d['then']}"),
                escape_text(d["because"]) if d["because"]
                else "<span class='nodata'>no reason given</span>",
            ]
            for d in view.declines
        ],
    )
    return (
        f"<h1>{escape_text(view.ref)} — {escape_text(view.title)}</h1>"
        f"<div class='panel'>{statement}</div>"
        f"<h2>The mechanism</h2>{story}"
        f"<h2>The record</h2><div class='panel'>{record}</div>"
        "<p class='mono'>The training occurrence is excluded from every figure above. "
        "Only predictions the mechanism sealed before the outcome, on occurrences it "
        "was not found on, count.</p>"
        f"<h2>What the agent was shown</h2>{evidence}"
        f"<h2>By instrument</h2>{by_instrument}"
        f"<h2>Predictions</h2>{predictions}"
        f"<h2>Paper trades</h2>{trades}"
        f"<h2>Others shown the same trigger, who declined</h2>{declines}"
    )


def world_page(session: Session) -> str:
    view = proj.world_view(session)
    kinds = _rows(
        ["kind", "events"], [[escape_text(k["kind"]), str(k["count"])] for k in view.by_kind]
    )
    recent = _rows(
        ["at", "kind", "entity", "payload", "source"],
        [
            [
                _when(e["at"]),
                escape_text(e["kind"]),
                escape_text(e["entity"]),
                escape_text(e["payload"][:160]),
                escape_text(e["source"][:60]),
            ]
            for e in view.recent
        ],
    )
    return (
        "<h1>The World</h1>"
        "<p class='mono'>Entities, a typed immutable event stream, and relations "
        "between them. Price is one event type among many and only its notable "
        "moments enter here; the bars stay in their recordings. What is in the "
        "stream is what the company could legitimately reach: the venue's own "
        "catalogue, and what can be derived deterministically from a recording.</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("entities", figure_span(view.entities)),
                ("events", figure_span(view.events)),
                ("relations", figure_span(view.relations)),
            ]
        )
        + "</div>"
        f"<h2>By kind</h2>{kinds}"
        f"<h2>Recent</h2>{recent}"
    )


def workshop_page(session: Session) -> str:
    view = proj.workshop_view(session)
    campaigns = (
        "<h2>Campaigns</h2>"
        "<p class='mono'>A campaign declares how many designs it will let "
        "itself try <em>before</em> it tries any, and the database refuses to "
        "change that once it has started. The column that matters is the last "
        "one: the best result minus what a search of that width returns from "
        "noise alone. A campaign with a negative surplus found nothing, and "
        "found it expensively.</p>"
        + _rows(
            [
                "ref",
                "desk",
                "attempts",
                "designs declared",
                "best",
                "observed",
                "expected by chance",
                "surplus",
            ],
            [
                [
                    escape_text(row["ref"]),
                    escape_text(row["desk"]),
                    f"{row['attempts']} of {row['budget']}",
                    str(row["width"]),
                    escape_text(row["best"]),
                    escape_text(row["observed"]),
                    escape_text(row["expected"]),
                    escape_text(row["surplus"])
                    if row["survives"]
                    else f"<b>{escape_text(row['surplus'])}</b>",
                ]
                for row in view.campaigns
            ],
        )
        if view.campaigns
        else ""
    )
    table = _rows(
        ["ref", "agent", "desk", "the rule", "verdict", "beat the baselines", "cells"],
        [
            [
                escape_text(row["ref"]),
                f"<a href='/agent/{escape_text(row['agent'])}'>{escape_text(row['agent'])}</a>",
                escape_text(row["desk"]),
                escape_text(row["design"]),
                _pill(row["verdict"]),
                "yes" if row["beat"] else "<b>no</b>",
                str(row["cells"]),
            ]
            for row in view.rows
        ],
    )
    return (
        "<h1>The Workshop</h1>"
        "<p class='mono'>Where the company tries to <em>create</em> a strategy "
        "rather than sift a corpus for one. Every attempt is here, including "
        "the ones that went nowhere -- a workshop showing only its successes "
        "would answer the one question it exists to answer with the one number "
        "that cannot answer it.</p>"
        "<div class='panel'>"
        + _kv(
            [
                ("attempts", figure_span(view.attempts)),
                ("beat every baseline", figure_span(view.beat_a_baseline)),
                ("survived the search", figure_span(view.survived_selection)),
                ("designs declared", str(view.designs_searched)),
            ]
        )
        + "</div>"
        + campaigns
        + "<h2>Attempts</h2>"
        "<p class='mono'>An attempt declares the whole space it chose from, not "
        "the one design it ran. Authoring from a menu is cheap, and a company "
        "that authored until something passed would be mining parameters with a "
        "rationale attached. The reasoner behind the seat is a deterministic "
        "stand-in, not a model, and every desk runs on fixtures.</p>" + table
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
