"""Methods, their fitness, and the daily step that replaces the failing ones."""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import sha256_of
from aurelis.core.enums import Actor, EventKind, ModelTier
from aurelis.core.ids import RefKind, uuid7
from aurelis.evolution.tables import AgentMethod
from aurelis.platform.db.refs import allocate_ref

__all__ = [
    "COIN_TOSS",
    "EVOLVE_EVERY",
    "METHOD_FORM",
    "MIN_VIEWS",
    "EvolutionRun",
    "Fitness",
    "adopt_method",
    "current_method",
    "evolve",
    "evolution_due",
    "fitness_of",
    "method_line",
]

COIN_TOSS = Decimal("0.25")
"""The Brier score of saying 0.5 every time. A view that cannot beat it has
told the company nothing it could not get by flipping a coin."""

MIN_VIEWS = 20
"""Scored views a method needs before its fitness is judged at all."""

EVOLVE_EVERY = dt.timedelta(hours=24)
"""How often the company reviews its methods."""

METHOD_MAX = 900

METHOD_FORM = (
    "Reply in exactly this form and nothing else:\n"
    "METHOD: <how to form a view on a market, in at most 120 words: what to look "
    "at, what to ignore, when to say nothing, how to set the confidence. Written "
    "as instructions to the agent who will use it>\n"
    "BECAUSE: <why this should score better than the record shows, in one or two "
    "sentences>\n"
)

_FIELD = re.compile(r"^\s*(METHOD|BECAUSE)\s*:\s*(.*)$", re.I)


@dataclass(frozen=True, slots=True)
class Fitness:
    """How a method has scored, forward, since it was adopted."""

    agent_ref: str
    method_ref: str | None
    views: int
    brier: Decimal | None
    error: Decimal | None
    """One standard error of the mean Brier."""

    @property
    def verdict(self) -> str:
        if self.brier is None or self.views < MIN_VIEWS or self.error is None:
            return "unproven"
        if self.brier - COIN_TOSS > self.error:
            return "failing"
        if COIN_TOSS - self.brier > self.error:
            return "thriving"
        return "chance"

    def describe(self) -> str:
        if self.brier is None:
            return f"{self.agent_ref}: no scored view under this method yet"
        return (
            f"{self.agent_ref}: {self.views} scored views, Brier {self.brier} "
            f"(standard error {self.error}) against {COIN_TOSS} for a coin toss: {self.verdict}"
        )


def current_method(session: Session, agent_ref: str) -> AgentMethod | None:
    return session.execute(
        sa.select(AgentMethod)
        .where(AgentMethod.agent_ref == agent_ref)
        .order_by(AgentMethod.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def method_line(session: Session, agent_ref: str) -> str:
    """The method as it goes into the agent's identity at a seat, or ``""``."""
    method = current_method(session, agent_ref)
    if method is None:
        return ""
    return (
        f"\n\nYour method (version {method.version}, adopted "
        f"{method.adopted_at:%Y-%m-%d}; the company replaces a method that scores "
        f"worse than a coin toss): {method.text}"
    )


def _scored_briers(session: Session, agent_ref: str, since: dt.datetime | None) -> list[Decimal]:
    """The Brier of every own view the agent sealed since ``since`` that has scored."""
    from aurelis.judgement.tables import Thesis

    query = sa.select(Thesis.brier).where(
        Thesis.agent_ref == agent_ref,
        Thesis.mechanism_ref.is_(None),
        Thesis.scored_at.is_not(None),
        Thesis.brier.is_not(None),
    )
    if since is not None:
        query = query.where(Thesis.sealed_at >= since)
    return [Decimal(str(b)) for b in session.execute(query).scalars()]


def _worst_views(
    session: Session, agent_ref: str, since: dt.datetime | None, *, limit: int = 6
) -> list[dict[str, str]]:
    """The agent's worst-scored own views under the method, for its revision."""
    from aurelis.judgement.tables import Thesis

    query = sa.select(Thesis).where(
        Thesis.agent_ref == agent_ref,
        Thesis.mechanism_ref.is_(None),
        Thesis.scored_at.is_not(None),
        Thesis.brier.is_not(None),
    )
    if since is not None:
        query = query.where(Thesis.sealed_at >= since)
    rows = sorted(
        session.execute(query).scalars(), key=lambda t: Decimal(str(t.brier)), reverse=True
    )[:limit]
    return [
        {
            "instrument": t.instrument,
            "said": f"{t.direction} over {t.horizon_hours}h at {t.confidence}",
            "happened": "up" if t.outcome else "down",
            "brier": str(t.brier),
            "thesis": " ".join(str(t.thesis).split())[:200],
        }
        for t in rows
    ]


def fitness_of(session: Session, agent_ref: str) -> Fitness:
    method = current_method(session, agent_ref)
    since = method.adopted_at if method is not None else None
    briers = _scored_briers(session, agent_ref, since)
    if not briers:
        return Fitness(agent_ref, method.ref if method else None, 0, None, None)
    n = len(briers)
    mean = sum(briers, Decimal(0)) / n
    variance = sum(((b - mean) ** 2 for b in briers), Decimal(0)) / max(n - 1, 1)
    error = Decimal(str(math.sqrt(float(variance) / n)))
    q = Decimal("0.0001")
    return Fitness(
        agent_ref, method.ref if method else None, n, mean.quantize(q), error.quantize(q)
    )


def adopt_method(
    session: Session,
    *,
    agent_ref: str,
    text: str,
    reason: str,
    authored_by: str,
    baseline: Fitness | None,
    ledger: Any = None,
    at: dt.datetime,
) -> AgentMethod:
    previous = current_method(session, agent_ref)
    cleaned = " ".join(text.split())[:METHOD_MAX]
    row = AgentMethod(
        method_id=uuid7(),
        ref=allocate_ref(session, RefKind.METHOD),
        agent_ref=agent_ref,
        version=(previous.version + 1) if previous is not None else 1,
        text=cleaned,
        reason=" ".join(reason.split())[:600],
        parent_ref=previous.ref if previous is not None else None,
        authored_by=authored_by,
        baseline_views=baseline.views if baseline is not None else 0,
        baseline_brier=str(baseline.brier) if baseline and baseline.brier is not None else None,
        adopted_at=at,
        digest=sha256_of({"agent": agent_ref, "text": cleaned, "at": at.isoformat()}),
    )
    session.add(row)
    session.flush()
    if ledger is not None:
        ledger.append(
            session,
            kind=EventKind.METHOD_ADOPTED,
            actor=authored_by,
            subject=row.ref,
            payload={
                "agent": agent_ref,
                "version": row.version,
                "authored_by": authored_by,
                "replaces": row.parent_ref,
                "baseline_views": row.baseline_views,
                "baseline_brier": row.baseline_brier,
                "method": cleaned[:300],
            },
            at=at,
        )
    return row


def _parse(text: str) -> tuple[str, str] | None:
    fields: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).upper()
            fields[current] = match.group(2).strip()
        elif current and line.strip():
            fields[current] = f"{fields[current]} {line.strip()}".strip()
    method = fields.get("METHOD", "").strip()
    because = fields.get("BECAUSE", "").strip()
    if len(method) < 40 or len(because) < 10:
        return None
    return method, because


@dataclass(frozen=True, slots=True)
class EvolutionRun:
    fitness: tuple[Fitness, ...]
    adopted: tuple[str, ...]
    refused: tuple[str, ...]
    calls: int

    def describe(self) -> str:
        failing = [f.agent_ref for f in self.fitness if f.verdict == "failing"]
        thriving = [f.agent_ref for f in self.fitness if f.verdict == "thriving"]
        return (
            f"evolution: {len(self.fitness)} methods measured; failing "
            f"{', '.join(failing) or 'none'}; thriving {', '.join(thriving) or 'none'}; "
            f"{len(self.adopted)} new method(s) adopted"
            + (f", {len(self.refused)} unreadable" if self.refused else "")
        )


def evolution_due(session: Session, at: dt.datetime) -> bool:
    from aurelis.platform.db.tables import Event

    last = session.execute(
        sa.select(sa.func.max(Event.created_at)).where(Event.kind == EventKind.EVOLUTION_RAN.value)
    ).scalar()
    if last is None:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=dt.UTC)
    return at - last >= EVOLVE_EVERY


_SYSTEM = (
    "You are an analyst at a research company whose analysts state forward views "
    "on markets, sealed before the outcome, and are measured by the Brier score of "
    "those views against 0.25 for a coin toss. A method that scores worse than a "
    "coin toss is replaced. You are asked to write the replacement. Write a method "
    "an analyst can follow at every seat: specific about what to look at and what "
    "to ignore, explicit about when to say nothing, and honest about confidence -- "
    "most views should sit close to 0.55 unless the evidence is unusual. Abstaining "
    "is always allowed and is not penalised."
)


def evolve(runtime: Any, *, at: dt.datetime | None = None) -> EvolutionRun:
    """Measure every judging agent's method and replace those that are failing."""
    from aurelis.agents.interpret import render_material
    from aurelis.autonomy.agenda import _judges
    from aurelis.platform.llm.routing import model_for
    from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

    moment = at or runtime.clock.now()
    adopted: list[str] = []
    refused: list[str] = []
    calls = 0
    with runtime.database.session() as session:
        judges = _judges(session)
        fitness = tuple(fitness_of(session, a.ref) for a in judges)
    thriving = sorted(
        (f for f in fitness if f.verdict == "thriving"),
        key=lambda f: (f.brier or COIN_TOSS, f.agent_ref),
    )
    for fit in fitness:
        if fit.verdict != "failing":
            continue
        teacher = next((t for t in thriving if t.agent_ref != fit.agent_ref), None)
        author = teacher.agent_ref if teacher is not None else fit.agent_ref
        with runtime.database.session() as session:
            own = current_method(session, fit.agent_ref)
            since = own.adopted_at if own is not None else None
            material: dict[str, Any] = {
                "the_analyst": fit.agent_ref,
                "its_method": own.text if own is not None else "none written: its charter only",
                "its_record": fit.describe(),
                "its_worst_calls": [
                    f"{v['instrument']}: said {v['said']}, it went {v['happened']}, Brier "
                    f"{v['brier']}. Why it said so: {v['thesis']}"
                    for v in _worst_views(session, fit.agent_ref, since)
                ],
            }
            if teacher is not None:
                taught = current_method(session, teacher.agent_ref)
                material["a_colleague_who_beats_the_coin_toss"] = teacher.describe()
                material["the_colleagues_method"] = (
                    taught.text if taught is not None else "none written: its charter only"
                )
                ask = (
                    f"Write the method {fit.agent_ref} should use from now on. You are "
                    f"{teacher.agent_ref}, and your views beat a coin toss; its do not."
                )
            else:
                ask = (
                    f"You are {fit.agent_ref}. Your views score worse than a coin toss and "
                    "no colleague does better than chance. Write the method you will use "
                    "from now on, from your own worst calls."
                )
            rendered = f"{render_material(material)}\n\n{ask}\n\n{METHOD_FORM}"
            tier = ModelTier.HIGH
            response = runtime.provider.complete(
                session,
                LlmRequest(
                    model=ModelRef(
                        provider=runtime.provider.name,
                        model=model_for(runtime.provider.name, tier),
                        tier=tier,
                        max_tokens=500,
                    ),
                    system=_SYSTEM,
                    messages=(Message("user", rendered),),
                    actor=author,
                ),
            )
            calls += 1
            parsed = _parse(response.text)
            if parsed is None:
                refused.append(fit.agent_ref)
                continue
            text, because = parsed
            row = adopt_method(
                session,
                agent_ref=fit.agent_ref,
                text=text,
                reason=because,
                authored_by=author,
                baseline=fit,
                ledger=runtime.ledger,
                at=moment,
            )
            adopted.append(row.ref)
    run = EvolutionRun(fitness, tuple(adopted), tuple(refused), calls)
    with runtime.database.session() as session:
        runtime.ledger.append(
            session,
            kind=EventKind.EVOLUTION_RAN,
            actor=Actor.SYSTEM,
            subject="evolution",
            payload={
                "fitness": [
                    {
                        "agent": f.agent_ref,
                        "method": f.method_ref,
                        "views": f.views,
                        "brier": None if f.brier is None else str(f.brier),
                        "verdict": f.verdict,
                    }
                    for f in fitness
                ],
                "adopted": list(adopted),
                "refused": list(refused),
            },
            at=moment,
        )
    return run
