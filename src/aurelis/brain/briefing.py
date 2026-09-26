"""What every agent reads before it answers: the shared brain, as a briefing.

Two parts, and they are kept apart because they are different kinds of thing:

``record``
    Derived from the database on every read, deterministically: the
    mechanisms under test and their verdicts, the retired ones and why, the
    patterns the agents declined most, the company's calibration, the paper
    book. Its figures are the record's, so the figure guard lets an agent
    cite them.

``notes``
    What agents and the operator chose to leave for the company. Opinions,
    attributed, and not evidence: the figure guard does not accept a number
    that only appears in a note.

The briefing has a budget. Every seat carries it, so every character in it is
paid for on every call; a section that grows is cut, newest kept, and the cut
is said.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.brain.notes import notes_about, recent_notes
from aurelis.brain.tables import BrainNote

__all__ = [
    "BRAIN_RULE",
    "Briefing",
    "briefing",
    "company_brief",
    "declined_patterns",
    "system_with_brain",
    "topic_block",
]

BRAIN_RULE = (
    "SHARED BRAIN. Every agent in the company reads this same brain, and what "
    "you leave in a NOTE is added to it for the others. The 'record' part is "
    "derived from the company's own database: you may cite its figures. The "
    "'notes' are colleagues' and the operator's opinions: weigh them, argue "
    "with them, but do not cite a figure that appears only in a note. Do not "
    "restate a mechanism the record says was retired, or a pattern colleagues "
    "declined, unless you have a reason they did not."
)

_RECORD_BUDGET = 2200
_NOTES_BUDGET = 900
_Q = Decimal("0.001")


@dataclass(frozen=True, slots=True)
class Briefing:
    record: str
    notes: str

    def text(self) -> str:
        parts = [BRAIN_RULE, "", "Record:", self.record or "  (nothing recorded yet)"]
        if self.notes:
            parts += ["", "Notes:", self.notes]
        return "\n".join(parts)


def _clip(lines: list[str], budget: int) -> str:
    out: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > budget:
            out.append(f"  (and {len(lines) - len(out)} more, cut for length)")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def _dec(value: Any) -> str:
    if value is None:
        return "none"
    return str(Decimal(str(value)).quantize(_Q))


def _payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        loaded = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def declined_patterns(session: Session, *, limit: int = 5) -> list[tuple[str, int, str]]:
    """Patterns the agents declined to state a mechanism for, most-declined
    first: ``(pattern, how many declines, one reason)``."""
    rows = session.execute(
        sa.text("SELECT payload FROM events WHERE kind = :kind ORDER BY seq DESC LIMIT 600"),
        {"kind": "mechanism.declined"},
    ).all()
    counts: dict[str, int] = {}
    reason: dict[str, str] = {}
    for (raw,) in rows:
        payload = _payload(raw)
        trigger = str(payload.get("trigger", ""))
        then = str(payload.get("then", ""))
        if not trigger:
            continue
        key = f"{trigger} then {then}" if then else trigger
        counts[key] = counts.get(key, 0) + 1
        because = " ".join(str(payload.get("because", "")).split())
        if because and key not in reason:
            reason[key] = because
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [(key, n, reason.get(key, "")) for key, n in ranked]


_CACHE: dict[tuple[Any, ...], str] = {}


def _fingerprint(session: Session) -> tuple[Any, ...]:
    from aurelis.judgement.tables import Thesis
    from aurelis.mechanism.tables import Mechanism, MechanismTrade

    return (
        str(session.get_bind().engine.url),
        tuple(
            session.execute(
                sa.select(sa.func.count(), sa.func.max(Mechanism.retired_at)).select_from(Mechanism)
            ).one()
        ),
        session.execute(
            sa.select(sa.func.count()).select_from(Thesis).where(Thesis.scored_at.is_not(None))
        ).scalar(),
        tuple(
            session.execute(
                sa.select(sa.func.count(), sa.func.max(MechanismTrade.closed_at)).select_from(
                    MechanismTrade
                )
            ).one()
        ),
        session.execute(
            sa.text("SELECT max(seq) FROM events WHERE kind = 'mechanism.declined'")
        ).scalar(),
    )


def company_brief(session: Session) -> str:
    """The record part of the brain. Cached until the record it reads changes."""
    key = _fingerprint(session)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    text = _company_brief(session)
    if len(_CACHE) > 32:
        _CACHE.clear()
    _CACHE[key] = text
    return text


def _short(text: str, limit: int) -> str:
    """One line, cut at a word boundary with an ellipsis if it runs long."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _company_brief(session: Session) -> str:
    """Most important first, so a cut for length loses the least: the
    mechanisms under test, the company's calibration, the paper book, then
    what was retired and what was declined."""
    from aurelis.judgement.tables import Thesis
    from aurelis.mechanism.library import Mechanisms
    lines: list[str] = []
    statuses = Mechanisms().statuses(session)
    active = [s for s in statuses if not s.retired]
    retired = [s for s in statuses if s.retired]
    if active:
        lines.append("Mechanisms under test (out-of-sample, scored against the drift):")
        for status in active:
            m = status.mechanism
            state = (
                "CANDIDATE SCHEME, trading on paper"
                if status.is_scheme
                else ("gathering" if not status.enough else status.verdict)
            )
            record = (
                f"{status.scored} scored, {status.calibration.hits} right, Brier "
                f"{_dec(status.calibration.mean_brier)} vs drift {_dec(status.base_rate_brier)}, "
                f"{status.episodes} episodes"
                if status.scored
                else "no prediction scored yet"
            )
            lines.append(
                f"- {m.ref} ({m.agent_ref}) {m.fires_on} -> {m.direction} "
                f"{m.horizon_hours}h: {state}; {record}"
            )

    views = session.execute(
        sa.select(sa.func.count(), sa.func.avg(sa.cast(Thesis.brier, sa.Float)))
        .select_from(Thesis)
        .where(Thesis.mechanism_ref.is_(None), Thesis.scored_at.is_not(None))
    ).one()
    if views[0]:
        best = session.execute(
            sa.select(
                Thesis.agent_ref, sa.func.count(), sa.func.avg(sa.cast(Thesis.brier, sa.Float))
            )
            .where(Thesis.mechanism_ref.is_(None), Thesis.scored_at.is_not(None))
            .group_by(Thesis.agent_ref)
            .having(sa.func.count() >= 10)
            .order_by(sa.func.avg(sa.cast(Thesis.brier, sa.Float)))
            .limit(1)
        ).first()
        line = (
            f"Agents' own views: {views[0]} scored, company Brier {_dec(views[1])} "
            "against 0.250 for a coin toss"
        )
        if best is not None:
            line += f"; best calibrated {best[0]} at {_dec(best[2])} over {best[1]}"
        lines.append(line + ".")

    from aurelis.autonomy.agenda import _judges
    from aurelis.evolution.methods import current_method, fitness_of

    methods: list[str] = []
    for agent in _judges(session):
        fit = fitness_of(session, agent.ref)
        if fit.verdict == "unproven":
            continue
        method = current_method(session, agent.ref)
        version = f"method v{method.version}" if method is not None else "charter only"
        methods.append(f"{agent.ref} {fit.verdict} ({version}, Brier {fit.brier} over {fit.views})")
    if methods:
        lines.append("Analysts under their current methods: " + "; ".join(methods) + ".")

    from aurelis.mechanism.paper import pnl_of

    books = [pnl_of(session, s.mechanism.ref) for s in statuses]
    trades = sum(b["trades"] for b in books)
    if trades:
        closed = sum(b["closed"] - b["late"] for b in books)
        pnl = sum((b["pnl"] for b in books), Decimal(0))
        late = sum(b["late"] for b in books)
        line = (
            f"Paper book: {closed} round trips closed at their horizon, realised P&L {pnl}; "
            f"{sum(b['open'] for b in books)} open."
        )
        if late:
            late_pnl = sum((b["late_pnl"] for b in books), Decimal(0))
            line += (
                f" {late} more were held past their horizon by an outage ({late_pnl}) "
                "and are not any mechanism's result."
            )
        lines.append(line)

        from aurelis.mechanism.earnings import earnings_board

        judged = [e for e in earnings_board(session).values() if e.round_trips]
        if judged:
            lines.append(
                "After costs, by episode: "
                + "; ".join(
                    f"{e.mechanism_ref} {e.pnl} over {e.episodes} episode(s), {e.verdict}"
                    for e in judged
                )
                + "."
            )

    if retired:
        lines.append("Retired, and why (do not restate without a new reason):")
        for status in retired[-6:]:
            m = status.mechanism
            lines.append(
                f"- {m.ref} {m.fires_on} -> {m.direction}: {_short(m.retired_reason, 110)}"
            )
    declined = declined_patterns(session, limit=4)
    if declined:
        lines.append("Patterns colleagues declined most:")
        for pattern, n, because in declined:
            lines.append(f"- {pattern} ({n} declines): {_short(because, 110)}")
    return _clip(lines, _RECORD_BUDGET)


def _note_line(note: BrainNote) -> str:
    who = "the operator" if note.kind == "operator" else note.author
    about = f" [{', '.join(note.topics[:3])}]" if note.topics else ""
    return f"- {note.ref} from {who}{about}: {note.text}"


def topic_block(session: Session, topics: tuple[str, ...] | list[str], *, limit: int = 5) -> str:
    """The notes about what this seat is looking at, as lines; empty if none."""
    found = notes_about(session, topics, limit=limit)
    return _clip([_note_line(n) for n in found], _NOTES_BUDGET) if found else ""


def briefing(session: Session, topics: tuple[str, ...] | list[str] = ()) -> Briefing:
    """The brain for one seat: the record, then the notes on its topics and
    the newest others, operator notes first among equals."""
    record = company_brief(session)
    picked: list[BrainNote] = []
    seen: set[str] = set()
    for note in notes_about(session, topics, limit=4) if topics else []:
        picked.append(note)
        seen.add(note.ref)
    recent = recent_notes(session, limit=30)
    for note in sorted(recent, key=lambda n: n.kind != "operator"):
        if len(picked) >= 8:
            break
        if note.ref not in seen:
            picked.append(note)
            seen.add(note.ref)
    return Briefing(record=record, notes=_clip([_note_line(n) for n in picked], _NOTES_BUDGET))


def system_with_brain(system: str, identity: str, brain: Briefing) -> str:
    """A seat's system prompt with the shared brain after who is sitting."""
    head = f"{system}\n\n{identity}" if identity else system
    return f"{head}\n\n{brain.text()}"
