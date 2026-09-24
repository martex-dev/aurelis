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
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
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
    text = str(value if value is not None else "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


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


def _pages(session: Session, at: dt.datetime) -> dict[str, str]:
    from aurelis.agents.tables import Agent
    from aurelis.judgement.tables import Thesis
    from aurelis.mechanism.library import Mechanisms
    from aurelis.service.tables import ServiceCycle

    pages: dict[str, str] = {}
    brain = briefing(session)
    statuses = Mechanisms().statuses(session)
    notes = recent_notes(session, limit=400)
    agents = {a.ref: a for a in session.execute(sa.select(Agent)).scalars()}

    # -- Home
    declined = declined_patterns(session, limit=10)
    home = [
        _front({"title": "Aurelis shared brain", "generated": at.isoformat()}),
        "# Aurelis — the shared brain\n",
        _BANNER,
        "Every agent reads this page's *record* and *notes* before it answers a seat.\n",
        "## Record\n",
        _linkify(brain.record) or "_Nothing recorded yet._",
        "\n## Notes\n",
        _linkify(brain.notes)
        or "_No notes yet. Agents add them with a NOTE line; you add "
        "them by dropping a file in [[Inbox/README|Inbox]]._",
        "\n## Where to look\n",
        "- [[Declines]] — every pattern the agents refused, and why",
        f"- [[Journal/{at.date().isoformat()}|Today's journal]] — what the service did",
        "- `Mechanisms/`, `Agents/`, `Notes/`, `Instruments/` — a page each",
    ]
    pages["Home.md"] = "\n".join(home) + "\n"

    # -- Mechanisms
    for status in statuses:
        m = status.mechanism
        verdict = f"retired: {m.retired_reason}" if status.retired else status.verdict
        body = [
            _front(
                {
                    "ref": m.ref,
                    "status": "retired" if status.retired else status.verdict,
                    "fires_on": m.fires_on,
                    "direction": m.direction,
                    "horizon_hours": m.horizon_hours,
                    "desk": m.desk,
                    "stated_by": m.agent_ref,
                    "tags": ["mechanism", "retired" if status.retired else "active"],
                }
            ),
            f"# {m.ref} — {m.title}\n",
            _BANNER,
            f"Stated by [[{m.agent_ref}]] on {m.stated_at:%Y-%m-%d}. Fires on `{m.fires_on}`, "
            f"predicts **{m.direction}** over {m.horizon_hours}h at {m.confidence}.\n",
            f"**Verdict:** {verdict}\n",
            f"**Record:** {status.predictions} predictions, {status.scored} scored, "
            f"{status.calibration.hits} right; Brier {status.calibration.mean_brier} against a "
            f"drift of {status.base_rate_brier}; {status.episodes} independent episodes.\n",
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

    # -- Agents
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
        body = [
            _front(
                {
                    "ref": ref,
                    "aliases": [agent.handle],
                    "department": str(agent.department),
                    "tags": ["agent"],
                }
            ),
            f"# {agent.handle} ({ref})\n",
            _BANNER,
            f"{str(agent.department).replace('_', ' ').title()}. "
            f"Views scored: {n}; mean Brier {brier if brier is not None else 'none yet'} "
            "(0.25 is a coin toss).\n",
        ]
        if stated:
            body += ["## Mechanisms stated\n"] + [f"- [[{m.ref}]] {m.title}" for m in stated]
        if written:
            body += ["\n## Notes left for the company\n"] + [
                f"- [[{note.ref}]] {note.text}" for note in written[:30]
            ]
        pages[f"Agents/{ref}.md"] = "\n".join(body) + "\n"

    # -- Notes, and the instruments they name
    instruments: dict[str, list[BrainNote]] = {}
    for note in notes:
        who = "the operator" if note.kind == "operator" else f"[[{note.author}]]"
        topics = note.topics or []
        body = [
            _front(
                {
                    "ref": note.ref,
                    "author": note.author,
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
        for topic in topics:
            if "-" in topic and topic.upper() == topic or ":" in topic:
                instruments.setdefault(topic, []).append(note)
    for key, about in sorted(instruments.items())[:120]:
        body = [
            _front({"instrument": key, "aliases": [key], "tags": ["instrument"]}),
            f"# {key}\n",
            _BANNER,
            "## Notes\n",
        ] + [f"- [[{n.ref}]] {n.text}" for n in about[:30]]
        pages[f"Instruments/{_safe(key)}.md"] = "\n".join(body) + "\n"

    # -- Declines
    decline_page = [
        _front({"title": "Declines", "tags": ["declines"]}),
        "# What the agents refused to call a mechanism, and why\n",
        _BANNER,
    ]
    for pattern, count, because in declined:
        decline_page += [f"## {pattern} — {count} decline(s)\n", because or "_no reason given_", ""]
    pages["Declines.md"] = "\n".join(decline_page) + "\n"

    # -- Journal: a page per day for the last week
    since = at - dt.timedelta(days=7)
    wakes = session.execute(
        sa.select(ServiceCycle)
        .where(ServiceCycle.started_at >= since)
        .order_by(ServiceCycle.started_at)
    ).scalars()
    days: dict[str, list[str]] = {}
    for wake in wakes:
        started = wake.started_at
        lines = days.setdefault(started.date().isoformat(), [])
        lines.append(f"## {started:%H:%M} UTC — {wake.ref}\n")
        lines += [f"- {part}" for part in (wake.note or "").split("; ") if part]
        lines.append("")
    for note in notes:
        when = note.written_at
        when = when if when.tzinfo else when.replace(tzinfo=dt.UTC)
        if when >= since:
            day = when.date().isoformat()
            days.setdefault(day, []).append(
                f"- note [[{note.ref}]] by {note.author}: {note.text[:120]}"
            )
    for day, lines in days.items():
        pages[f"Journal/{day}.md"] = (
            _front({"date": day, "tags": ["journal"]}) + f"# {day}\n\n" + "\n".join(lines) + "\n"
        )

    pages["Inbox/README.md"] = (
        "# Inbox — write to the shared brain\n\n"
        "Drop a Markdown file here. The next wake reads it into the shared brain as a "
        "note **from the operator**, and every agent reads it at every seat from then on.\n\n"
        "- Link what it is about with `[[BTC-USD]]`, `[[MEC-0001]]`, or tag it `#memecoin`: "
        "those become the note's topics, so it is shown first to agents looking at them.\n"
        "- Keep it short: the first 400 characters are kept.\n"
        "- The file is moved to `Inbox/Read` once read, so it is never read twice.\n"
        "- A note is an opinion, not evidence. Agents weigh it; they may not cite its "
        "figures as if the record had measured them.\n"
    )
    return pages


def _topic_link(topic: str) -> str:
    if _REF.fullmatch(topic):
        return f"[[{topic}]]"
    if ("-" in topic and topic.upper() == topic) or ":" in topic:
        return f"[[Instruments/{_safe(topic)}|{topic}]]"
    return f"`{topic}`"


def render_brain(session: Session, root: Path, *, at: dt.datetime) -> BrainExport:
    """Write the vault. A page whose content did not change is not rewritten,
    so Obsidian does not reload the vault every hour; a generated page nothing
    produces any more is removed. ``Inbox`` is never touched but for its README."""
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
    removed = 0
    keep = {str((root / p).resolve()) for p in pages}
    for folder in _OWNED:
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
