"""The shared brain as an Obsidian vault, and its inbox.

Open ``<workspace>/brain`` as a vault in Obsidian. ``Home`` is what every
agent reads; each mechanism, agent, note and instrument has a page, and they
link to each other, so the graph view shows who stated what, on what, and
what the company wrote about it. ``Journal`` has a page per day of what the
service did, wake by wake.

The vault is rendered from the database on every wake, and every generated
page is rewritten, so an edit made to one is lost; the page says so at the
top. The one way in is ``Inbox``: a Markdown file the operator drops there is
read by the next wake into the brain as a note from the operator, with its
``[[links]]`` and ``#tags`` as topics, and moved to ``Inbox/Read``. Every agent
then reads it at every seat, attributed to the operator. That is how a person
adds a thought to the brain without typing it into a terminal: the note has
an author and a time, like everything else in the record.

Three things are the operator's and are never overwritten or removed:
``Operator/`` (their own analysis), ``Dashboard.base`` (an Obsidian Bases view
over the pages' properties, seeded once) and ``History/`` (one snapshot of the
record per day, so a score can be followed over time; only today's is
rewritten). Journal pages are kept after they leave the seven-day window.

Every figure a page shows is also a property in its frontmatter, as a number,
so Bases can sort and filter on it.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.brain.briefing import briefing, declined_patterns
from aurelis.brain.notes import OPERATOR, recent_notes, write_note
from aurelis.brain.tables import BrainNote

__all__ = ["BrainExport", "ingest_inbox", "render_brain", "sync_brain"]

_BANNER = (
    "> [!info] Generated from the Aurelis record on every wake.\n"
    "> Edits here are overwritten. To add a thought to the shared brain, drop a "
    "Markdown file into [[Inbox/README|Inbox]].\n"
)
_OWNED = ("Mechanisms", "Agents", "Notes", "Instruments", "Journal")
_PRUNED = ("Mechanisms", "Agents", "Notes", "Instruments")
"""Folders whose stale pages are removed. Journal is written but never pruned:
a day that left the seven-day window is still what happened that day."""
_REF = re.compile(r"\b((?:MEC|AG|NOTE)-\d{4})\b")
_LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_TAG = re.compile(r"(?<![\w/])#([A-Za-z][\w.:\-]{1,60})")
_INBOX_MAX = 4000


@dataclass(frozen=True, slots=True)
class BrainExport:
    root: Path
    written: int
    unchanged: int
    removed: int
    ingested: tuple[str, ...]

    def describe(self) -> str:
        read = f", {len(self.ingested)} operator note(s) read" if self.ingested else ""
        return (
            f"brain: {self.written} page(s) written, {self.unchanged} unchanged, "
            f"{self.removed} removed{read}"
        )


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]


def _linkify(text: str) -> str:
    return _REF.sub(lambda m: f"[[{m.group(1)}]]", text)


def _front(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list | tuple):
            lines.append(f"{key}: [{', '.join(_yaml(v) for v in value)}]")
        else:
            lines.append(f"{key}: {_yaml(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _yaml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | Decimal):
        return str(value)
    text = str(value if value is not None else "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _num(value: Any, places: int = 3) -> float | None:
    """A figure rounded for a page: ``0.25063488372093023`` reads as ``0.251``."""
    if value is None:
        return None
    return round(float(value), places)


def _shown(value: Any, places: int = 3) -> str:
    rounded = _num(value, places)
    return "none yet" if rounded is None else f"{rounded:.{places}f}"


def _props(fields: dict[str, Any]) -> dict[str, Any]:
    """Frontmatter without the empty ones: a missing property sorts last in a
    Bases table, an empty string sorts as text."""
    return {k: v for k, v in fields.items() if v is not None}


# ------------------------------------------------------------------ the inbox


def ingest_inbox(
    session: Session, root: Path, *, ledger: Any = None, at: dt.datetime
) -> tuple[str, ...]:
    """Read every Markdown file in ``Inbox`` into the brain as an operator note.

    Its ``[[links]]`` and ``#tags`` become the note's topics. The file is moved
    to ``Inbox/Read`` with the note's ref in its name, whether or not it said
    enough to become a note, so it is never read twice. Returns the refs.
    """
    inbox = root / "Inbox"
    if not inbox.is_dir():
        return ()
    read = inbox / "Read"
    refs: list[str] = []
    for path in sorted(inbox.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")[:_INBOX_MAX]
        body = re.sub(r"^---\n.*?\n---\n", "", raw, flags=re.S)
        topics = [m.group(1).strip() for m in _LINK.finditer(body)]
        topics += [m.group(1) for m in _TAG.finditer(body)]
        topics = [t.split("/")[-1] for t in topics]
        text = _LINK.sub(lambda m: m.group(1).split("/")[-1], body)
        text = " ".join(text.replace("#", "").split())
        note = write_note(
            session,
            author=OPERATOR,
            text=text,
            topics=topics,
            source_ref=f"inbox:{path.name}",
            ledger=ledger,
            at=at,
        )
        read.mkdir(parents=True, exist_ok=True)
        stamp = at.strftime("%Y%m%d-%H%M")
        label = note.ref if note is not None else "not-a-note"
        path.replace(read / f"{stamp} {label} {path.name}")
        if note is not None:
            refs.append(note.ref)
    return tuple(refs)


# ------------------------------------------------------------------ the pages


def _mechanism_props(status: Any) -> dict[str, Any]:
    m = status.mechanism
    brier = _num(status.calibration.mean_brier)
    drift = _num(status.base_rate_brier)
    return _props(
        {
            "ref": m.ref,
            "status": "retired" if status.retired else status.verdict,
            "active": not status.retired,
            "scheme": bool(status.is_scheme),
            "fires_on": m.fires_on,
            "direction": m.direction,
            "horizon_hours": int(m.horizon_hours),
            "confidence": _num(m.confidence, 2),
            "desk": m.desk,
            "stated_by": m.agent_ref,
            "stated": f"{m.stated_at:%Y-%m-%d}",
            "predictions": int(status.predictions),
            "scored": int(status.scored),
            "hits": int(status.calibration.hits),
            "hit_rate": _num(status.calibration.hits / status.scored) if status.scored else None,
            "brier": brier,
            "drift": drift,
            "edge": _num(drift - brier) if brier is not None and drift is not None else None,
            "episodes": int(status.episodes),
            "episode_brier": _num(status.episode_brier),
            "episode_drift": _num(status.episode_base_rate_brier),
            "tags": ["mechanism", "retired" if status.retired else "active"],
        }
    )


def _split_wake(note: str) -> list[str]:
    """A wake's note, one part per step. Parts are joined with ``"; "`` but a
    step's own detail in parentheses may hold ``"; "`` too, so split only
    outside parentheses."""
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(note):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif ch == ";" and depth == 0 and note[i + 1 : i + 2] == " ":
            parts.append(note[start:i].strip())
            start = i + 2
    parts.append(note[start:].strip())
    return [p for p in parts if p]


_PROBLEM = re.compile(r"not read|refused|needs AURELIS_KEY|error|failed", re.I)


def _step(part: str) -> str:
    """The name of a wake step: ``bluesky`` for ``bluesky: 6 of 30 not read``."""
    return part.split(":", 1)[0].strip() if ":" in part else part


def _summary(part: str) -> tuple[str, list[str]]:
    """A problem part as its headline and its details: ``bluesky: 6 of 30 not
    read`` and the per-instrument reasons that were in parentheses."""
    cut = part.find(" (")
    if cut < 0 or not part.endswith(")"):
        return part, []
    details = [d.strip() for d in _split_wake(part[cut + 2 : -1].replace("\n", "; "))]
    return part[:cut], [d for d in details if d and not d.startswith("and ")]


def _journal_day(wakes: list[tuple[dt.datetime, str, str]], notes: list[str]) -> list[str]:
    """One day of the journal: the problems said once at the top, then each
    wake with what changed. A step that reads the same as the wake before it
    is counted, not repeated; a source that failed shows its headline, and
    each distinct reason appears once, under Problems."""
    problems: dict[str, None] = {}
    body: list[str] = []
    previous: dict[str, str] = {}
    for started, ref, note in wakes:
        body.append(f"## {started:%H:%M} UTC — {ref}\n")
        same = 0
        for part in _split_wake(note):
            step = _step(part)
            if previous.get(step) == part:
                same += 1
                continue
            previous[step] = part
            if _PROBLEM.search(part):
                headline, details = _summary(part)
                body.append(f"- ⚠ {headline}")
                for detail in details:
                    problems[" ".join(detail.split())] = None
            else:
                body.append(f"- {part}")
        if same:
            body.append(f"- _{same} step(s) unchanged since the previous wake_")
        body.append("")
    head: list[str] = []
    if problems:
        head += [
            "> [!warning]- Source problems today (each reason once)",
            *[f"> - {p}" for p in problems],
            "",
        ]
    if notes:
        body += ["## Notes written today\n", *notes, ""]
    return head + body


def _open_calls(session: Session) -> dict[str, list[Any]]:
    """Mechanism predictions not yet scored, by instrument, soonest first."""
    from aurelis.judgement.tables import Thesis

    rows = session.execute(
        sa.select(Thesis)
        .where(
            Thesis.mechanism_ref.is_not(None),
            Thesis.scored_at.is_(None),
            Thesis.mechanism_training.is_(False),
        )
        .order_by(Thesis.resolves_at)
    ).scalars()
    calls: dict[str, list[Any]] = {}
    for row in rows:
        calls.setdefault(row.instrument, []).append(row)
    return calls


def _recent_calls(session: Session, instruments: set[str]) -> dict[str, list[Any]]:
    """The last scored mechanism predictions on these instruments, newest first."""
    from aurelis.judgement.tables import Thesis

    if not instruments:
        return {}
    rows = session.execute(
        sa.select(Thesis)
        .where(
            Thesis.mechanism_ref.is_not(None),
            Thesis.scored_at.is_not(None),
            Thesis.instrument.in_(sorted(instruments)),
        )
        .order_by(Thesis.scored_at.desc())
        .limit(40 * len(instruments))
    ).scalars()
    recent: dict[str, list[Any]] = {}
    for row in rows:
        kept = recent.setdefault(row.instrument, [])
        if len(kept) < 10:
            kept.append(row)
    return recent


def _decline_reasons(session: Session) -> dict[str, tuple[int, int]]:
    """For each declined pattern: how many declines, and how many gave a reason."""
    import json

    rows = session.execute(
        sa.text("SELECT payload FROM events WHERE kind = :kind ORDER BY seq DESC LIMIT 600"),
        {"kind": "mechanism.declined"},
    ).all()
    out: dict[str, tuple[int, int]] = {}
    for (raw,) in rows:
        try:
            payload = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        trigger = str(payload.get("trigger", ""))
        if not trigger:
            continue
        then = str(payload.get("then", ""))
        key = f"{trigger} then {then}" if then else trigger
        total, reasoned = out.get(key, (0, 0))
        out[key] = (total + 1, reasoned + (1 if str(payload.get("because", "")).strip() else 0))
    return out


def _pages(session: Session, at: dt.datetime) -> dict[str, str]:
    from aurelis.agents.tables import Agent
    from aurelis.evolution.methods import fitness_of
    from aurelis.evolution.tables import AgentMethod
    from aurelis.judgement.tables import Thesis
    from aurelis.mechanism.library import Mechanisms
    from aurelis.service.tables import ServiceCycle

    pages: dict[str, str] = {}
    brain = briefing(session)
    statuses = Mechanisms().statuses(session)
    every_note = recent_notes(session, limit=None)
    notes = every_note[:400]
    agents = {a.ref: a for a in session.execute(sa.select(Agent)).scalars()}

    # -- Home
    declined = declined_patterns(session, limit=10)
    home = [
        _front({"title": "Aurelis shared brain", "generated": at.isoformat()}),
        "# Aurelis — the shared brain\n",
        _BANNER,
        "Every agent reads this page's *record* and *notes* before it answers a seat.\n",
        "> [!tip] Read the episodes, not the predictions",
        "> Predictions that fire in the same hours are one market event counted many",
        "> times. A mechanism's evidence is its **episodes**; [[Dashboard.base|the dashboard]]",
        "> sorts every mechanism by its edge over the drift (drift Brier − Brier).\n",
        "## Record\n",
        _linkify(brain.record) or "_Nothing recorded yet._",
        "\n## Notes\n",
        _linkify(brain.notes)
        or "_No notes yet. Agents add them with a NOTE line; you add "
        "them by dropping a file in [[Inbox/README|Inbox]]._",
        "\n## Where to look\n",
        "- [[Dashboard.base|Dashboard]] — mechanisms, agents and notes as sortable tables",
        "- [[Declines]] — every pattern the agents refused, and why",
        f"- [[Journal/{at.date().isoformat()}|Today's journal]] — what the service did",
        f"- [[History/{at.date().isoformat()}|Today's record]] — a snapshot per day in `History/`",
        "- `Operator/` — your own pages; the service never touches them",
        "- `Mechanisms/`, `Agents/`, `Notes/`, `Instruments/` — a page each",
    ]
    pages["Home.md"] = "\n".join(home) + "\n"

    # -- Mechanisms
    for status in statuses:
        m = status.mechanism
        verdict = f"retired: {m.retired_reason}" if status.retired else status.verdict
        body = [
            _front(_mechanism_props(status)),
            f"# {m.ref} — {m.title}\n",
            _BANNER,
            f"Stated by [[{m.agent_ref}]] on {m.stated_at:%Y-%m-%d}. Fires on `{m.fires_on}`, "
            f"predicts **{m.direction}** over {m.horizon_hours}h at {_shown(m.confidence, 2)}.\n",
            f"**Verdict:** {verdict}\n",
            f"**Record:** {status.predictions} predictions, {status.scored} scored, "
            f"{status.calibration.hits} right; Brier {_shown(status.calibration.mean_brier)} "
            f"against a drift of {_shown(status.base_rate_brier)}; "
            f"**{status.episodes} independent episode(s)**.\n",
        ]
        if status.scored and status.episodes and status.scored >= 10 * status.episodes:
            body.append(
                f"> [!warning] {status.scored} scored predictions but only "
                f"{status.episodes} episode(s): about {status.scored // status.episodes} "
                "predictions per market event. Read this record as "
                f"{status.episodes} observation(s), not {status.scored}.\n"
            )
        body += [
            "## Why it should work\n",
            m.why,
            "\n## Who is on the other side\n",
            m.other_side,
            "\n## How it dies\n",
            m.decay,
        ]
        about = [
            n for n in notes if m.ref in (n.topics or []) or m.trigger_kind in (n.topics or [])
        ]
        if about:
            body += ["\n## Notes\n"] + [f"- [[{n.ref}]] {n.text}" for n in about[:20]]
        pages[f"Mechanisms/{m.ref}.md"] = "\n".join(body) + "\n"

    # -- Agents: only those who have done something, so the graph is not a
    # ring of empty pages
    views = {
        ref: (n, brier)
        for ref, n, brier in session.execute(
            sa.select(
                Thesis.agent_ref, sa.func.count(), sa.func.avg(sa.cast(Thesis.brier, sa.Float))
            )
            .where(Thesis.mechanism_ref.is_(None), Thesis.scored_at.is_not(None))
            .group_by(Thesis.agent_ref)
        ).all()
    }
    for ref, agent in sorted(agents.items()):
        n, brier = views.get(ref, (0, None))
        stated = [s.mechanism for s in statuses if s.mechanism.agent_ref == ref]
        written = [note for note in notes if note.author == ref]
        history = list(
            session.execute(
                sa.select(AgentMethod)
                .where(AgentMethod.agent_ref == ref)
                .order_by(AgentMethod.version.desc())
            ).scalars()
        )
        if not (n or stated or written or history):
            continue
        fitness = fitness_of(session, ref) if history else None
        body = [
            _front(
                _props(
                    {
                        "ref": ref,
                        "aliases": [agent.handle],
                        "department": str(agent.department),
                        "views_scored": int(n),
                        "brier": _num(brier),
                        "vs_coin_toss": _num(0.25 - brier) if brier is not None else None,
                        "method_version": history[0].version if history else None,
                        "method_views": fitness.views if fitness else None,
                        "method_brier": _num(fitness.brier) if fitness else None,
                        "mechanisms_stated": len(stated),
                        "notes_written": len(written),
                        "tags": ["agent"],
                    }
                )
            ),
            f"# {agent.handle} ({ref})\n",
            _BANNER,
            f"{str(agent.department).replace('_', ' ').title()}. "
            f"Views scored: {n}; mean Brier {_shown(brier)} (0.250 is a coin toss).\n",
        ]
        if history:
            body += [
                "## Method\n",
                f"Version {history[0].version}, adopted {history[0].adopted_at:%Y-%m-%d}, "
                f"written by [[{history[0].authored_by}]]. "
                f"{fitness.describe() if fitness else ''}\n",
                history[0].text,
                "",
            ]
            for old in history[1:]:
                body.append(f"- v{old.version} ({old.adopted_at:%Y-%m-%d}): {old.text[:160]}")
            body.append("")
        if stated:
            body += ["## Mechanisms stated\n"] + [f"- [[{m.ref}]] {m.title}" for m in stated]
        if written:
            body += ["\n## Notes left for the company\n"] + [
                f"- [[{note.ref}]] {note.text}" for note in written[:30]
            ]
        pages[f"Agents/{ref}.md"] = "\n".join(body) + "\n"

    # -- Notes: every one ever written, so a [[NOTE-…]] link never breaks
    instruments: dict[str, list[BrainNote]] = {}
    for note in every_note:
        who = "the operator" if note.kind == "operator" else f"[[{note.author}]]"
        topics = note.topics or []
        body = [
            _front(
                {
                    "ref": note.ref,
                    "author": note.author,
                    "kind": note.kind,
                    "written": note.written_at.isoformat(),
                    "topics": topics,
                    "tags": ["note", note.kind],
                }
            ),
            f"# {note.ref}\n",
            f"From {who}, {note.written_at:%Y-%m-%d %H:%M} UTC, "
            f"while answering `{note.source_ref}`.\n",
            _linkify(note.text),
        ]
        if topics:
            body.append("\nAbout: " + ", ".join(_topic_link(t) for t in topics))
        pages[f"Notes/{note.ref}.md"] = "\n".join(body) + "\n"
    for note in notes:
        for topic in note.topics or []:
            if _is_instrument(topic):
                instruments.setdefault(topic, []).append(note)

    # -- Instruments: what the company is betting on it now, what it got
    # right lately, and what agents wrote about it
    open_calls = _open_calls(session)
    # At most 120 pages: the instruments with the most going on.
    busiest = sorted(
        set(instruments) | set(open_calls),
        key=lambda k: (-(len(open_calls.get(k, [])) + len(instruments.get(k, []))), k),
    )
    keys = sorted(busiest[:120])
    recent = _recent_calls(session, set(keys))
    for key in keys:
        calls = open_calls.get(key, [])
        done = recent.get(key, [])
        about = instruments.get(key, [])
        right = sum(1 for t in done if t.outcome == (t.direction == "up"))
        body = [
            _front(
                _props(
                    {
                        "instrument": key,
                        "aliases": [key],
                        "open_calls": len(calls),
                        "calls_up": sum(1 for t in calls if t.direction == "up"),
                        "calls_down": sum(1 for t in calls if t.direction == "down"),
                        "recent_scored": len(done),
                        "recent_right": right if done else None,
                        "notes": len(about),
                        "tags": ["instrument"],
                    }
                )
            ),
            f"# {key}\n",
            _BANNER,
        ]
        if calls:
            body += [
                "## Open mechanism calls\n",
                "| Mechanism | Calls | Since | Resolves | Reference close |",
                "|---|---|---|---|---|",
            ]
            for t in calls[:15]:
                body.append(
                    f"| [[{t.mechanism_ref}]] | {t.direction} at {_shown(t.probability_up, 2)} "
                    f"| {t.reference_at:%m-%d %H:%M} | {t.resolves_at:%m-%d %H:%M} "
                    f"| {t.reference_close} |"
                )
            if len(calls) > 15:
                body.append(f"\n_and {len(calls) - 15} more_")
            body.append("")
        if done:
            body += [
                f"## Last scored calls ({right} of {len(done)} right)\n",
                "| Mechanism | Called | Resolved | Close | Right | Brier |",
                "|---|---|---|---|---|---|",
            ]
            for t in done:
                ok = t.outcome == (t.direction == "up")
                body.append(
                    f"| [[{t.mechanism_ref}]] | {t.direction} | {t.resolves_at:%m-%d %H:%M} "
                    f"| {t.reference_close} → {t.resolution_close or '?'} "
                    f"| {'✓' if ok else '✗'} | {_shown(t.brier)} |"
                )
            body.append("")
        if about:
            body += ["## Notes\n"] + [f"- [[{n.ref}]] {n.text}" for n in about[:30]]
        pages[f"Instruments/{_safe(key)}.md"] = "\n".join(body) + "\n"

    # -- Declines
    reasons = _decline_reasons(session)
    decline_page = [
        _front({"title": "Declines", "tags": ["declines"]}),
        "# What the agents refused to call a mechanism, and why\n",
        _BANNER,
    ]
    for pattern, count, because in declined:
        total, reasoned = reasons.get(pattern, (count, 1 if because else 0))
        decline_page.append(f"## {pattern} — {count} decline(s)\n")
        if because:
            decline_page += [because, f"\n_{reasoned} of {total} recent declines gave a reason._"]
        else:
            decline_page.append(
                f"> [!question] None of the {total} recent declines gave a reason\n"
                "> The agents answered `MECHANISM: nothing` with no `BECAUSE` line, or the "
                "reply could not be read at all. A decline with no reason still stops the "
                "pattern being offered again, so it is worth checking these replies."
            )
        decline_page.append("")
    pages["Declines.md"] = "\n".join(decline_page) + "\n"

    # -- Journal: a page per day for the last week; older pages are kept
    since = at - dt.timedelta(days=7)
    wakes = session.execute(
        sa.select(ServiceCycle)
        .where(ServiceCycle.started_at >= since)
        .order_by(ServiceCycle.started_at)
    ).scalars()
    by_day: dict[str, list[tuple[dt.datetime, str, str]]] = {}
    for wake in wakes:
        by_day.setdefault(wake.started_at.date().isoformat(), []).append(
            (wake.started_at, wake.ref, wake.note or "")
        )
    day_notes: dict[str, list[str]] = {}
    for note in notes:
        when = note.written_at
        when = when if when.tzinfo else when.replace(tzinfo=dt.UTC)
        if when >= since:
            day_notes.setdefault(when.date().isoformat(), []).append(
                f"- {when:%H:%M} [[{note.ref}]] by {note.author}: {note.text[:120]}"
            )
    for day in sorted(set(by_day) | set(day_notes)):
        lines = _journal_day(by_day.get(day, []), sorted(day_notes.get(day, [])))
        pages[f"Journal/{day}.md"] = (
            _front({"date": day, "tags": ["journal"]}) + f"# {day}\n\n" + "\n".join(lines) + "\n"
        )

    # -- History: today's record, kept after today
    pages[f"History/{at.date().isoformat()}.md"] = _history(statuses, views, at)

    pages["Inbox/README.md"] = (
        "# Inbox — write to the shared brain\n\n"
        "Drop a Markdown file here. The next wake reads it into the shared brain as a "
        "note **from the operator**, and every agent reads it at every seat from then on.\n\n"
        "- Link what it is about with `[[BTC-USD]]`, `[[MEC-0001]]`, or tag it `#memecoin`: "
        "those become the note's topics, so it is shown first to agents looking at them.\n"
        "- Keep it short: the first 400 characters are kept, cut at a sentence.\n"
        "- The file is moved to `Inbox/Read` once read, so it is never read twice.\n"
        "- A note is an opinion, not evidence. Agents weigh it; they may not cite its "
        "figures as if the record had measured them.\n"
        "- Every agent reads it at every seat, so it steers the whole company. Prefer "
        'a question to test ("does MEC-0001 fail on breaks that reject the same bar?") '
        'over a call ("BTC goes up").\n'
        "- Your own analysis, which agents should not read, belongs in `Operator/`.\n"
    )
    return pages


def _history(statuses: list[Any], views: dict[str, tuple[int, Any]], at: dt.datetime) -> str:
    """One day's record as a table: rewritten through the day, then left alone."""
    lines = [
        _front({"date": at.date().isoformat(), "taken": at.isoformat(), "tags": ["history"]}),
        f"# Record on {at.date().isoformat()}\n",
        f"Last written {at:%H:%M} UTC. A new page is started each day; past days are never "
        "rewritten, so these pages are how a score is followed over time.\n",
        "## Mechanisms\n",
        "| Mechanism | Status | Scored | Right | Brier | Drift | Edge | Episodes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for status in statuses:
        p = _mechanism_props(status)
        lines.append(
            f"| [[{p['ref']}]] | {p['status']} | {p['scored']} | {p['hits']} "
            f"| {p.get('brier', '–')} | {p.get('drift', '–')} | {p.get('edge', '–')} "
            f"| {p['episodes']} |"
        )
    scored = [(ref, n, b) for ref, (n, b) in sorted(views.items()) if n]
    if scored:
        lines += [
            "\n## Agents' own views\n",
            "| Agent | Scored | Brier |",
            "|---|---|---|",
            *[f"| [[{ref}]] | {n} | {_shown(b)} |" for ref, n, b in scored],
        ]
    return "\n".join(lines) + "\n"


def _is_instrument(topic: str) -> bool:
    return ("-" in topic and topic.upper() == topic) or ":" in topic


def _topic_link(topic: str) -> str:
    if _REF.fullmatch(topic):
        return f"[[{topic}]]"
    if _is_instrument(topic):
        return f"[[Instruments/{_safe(topic)}|{topic}]]"
    return f"`{topic}`"


# ------------------------------------------------------------------ seeded once

_DASHBOARD = """\
# Aurelis dashboard — an Obsidian Bases view over the brain's properties.
# Seeded once by the service and then yours: it is never overwritten.
views:
  - type: table
    name: Mechanisms by edge
    filters:
      and:
        - file.inFolder("Mechanisms")
        - active == true
    order:
      - file.name
      - status
      - fires_on
      - direction
      - horizon_hours
      - scored
      - episodes
      - brier
      - drift
      - edge
      - stated_by
    sort:
      - property: edge
        direction: DESC
  - type: table
    name: Mechanisms with 10+ episodes
    filters:
      and:
        - file.inFolder("Mechanisms")
        - episodes >= 10
    order:
      - file.name
      - status
      - scored
      - episodes
      - brier
      - drift
      - edge
    sort:
      - property: edge
        direction: DESC
  - type: table
    name: Retired mechanisms
    filters:
      and:
        - file.inFolder("Mechanisms")
        - active == false
    order:
      - file.name
      - fires_on
      - direction
      - scored
      - episodes
      - brier
      - drift
  - type: table
    name: Agents by calibration
    filters:
      and:
        - file.inFolder("Agents")
    order:
      - file.name
      - aliases
      - department
      - views_scored
      - brier
      - vs_coin_toss
      - method_version
      - method_brier
      - mechanisms_stated
      - notes_written
    sort:
      - property: brier
        direction: ASC
  - type: table
    name: Instruments with open calls
    filters:
      and:
        - file.inFolder("Instruments")
        - open_calls > 0
    order:
      - file.name
      - open_calls
      - calls_up
      - calls_down
      - recent_scored
      - recent_right
      - notes
    sort:
      - property: open_calls
        direction: DESC
  - type: table
    name: Notes, newest first
    filters:
      and:
        - file.inFolder("Notes")
    order:
      - file.name
      - author
      - kind
      - topics
      - written
    sort:
      - property: written
        direction: DESC
"""

_OPERATOR_README = """\
# Operator — your own pages

The service never writes, rewrites or removes anything in this folder. Put your
own analysis, questions and trade ideas here and link to the generated pages
(`[[MEC-0001]]`, `[[BTC-USD]]`).

Agents do **not** read this folder. To tell every agent something, drop a note
in [[Inbox/README|Inbox]] instead.
"""

_SEEDS = {"Dashboard.base": _DASHBOARD, "Operator/README.md": _OPERATOR_README}


def _seed(root: Path) -> None:
    """Write the operator's files once; after that they are the operator's."""
    for relative, content in _SEEDS.items():
        path = root / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")


def render_brain(session: Session, root: Path, *, at: dt.datetime) -> BrainExport:
    """Write the vault. A page whose content did not change is not rewritten,
    so Obsidian does not reload the vault every hour; a generated page nothing
    produces any more is removed, except a journal day. ``Inbox`` is never
    touched but for its README; ``Operator``, ``History`` past today and
    ``Dashboard.base`` are the operator's."""
    root.mkdir(parents=True, exist_ok=True)
    pages = _pages(session, at)
    written = unchanged = 0
    for relative, content in pages.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8") == content:
            unchanged += 1
            continue
        path.write_text(content, encoding="utf-8", newline="\n")
        written += 1
    _seed(root)
    removed = 0
    keep = {str((root / p).resolve()) for p in pages}
    for folder in _PRUNED:
        for path in (root / folder).glob("*.md") if (root / folder).is_dir() else []:
            if str(path.resolve()) not in keep:
                path.unlink()
                removed += 1
    return BrainExport(root, written, unchanged, removed, ())


def sync_brain(
    runtime: Any, *, root: Path | None = None, at: dt.datetime | None = None
) -> BrainExport:
    """Read the inbox into the brain, then render the vault. One wake step."""
    moment = at or runtime.clock.now()
    target = root or (runtime.settings.workspace / "brain")
    with runtime.database.session() as session:
        refs = ingest_inbox(session, target, ledger=runtime.ledger, at=moment)
    with runtime.database.session() as session:
        export = render_brain(session, target, at=moment)
    return BrainExport(export.root, export.written, export.unchanged, export.removed, refs)
