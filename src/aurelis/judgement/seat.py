"""The judgement seat: an agent picks a market and states a view, on the record.

Two questions, two model calls, one row.

**Which market?** The agent is shown every instrument the company can resolve —
the ones it holds a recording of — with a software-computed summary of each,
and its own record so far. It picks one, or ``nothing``. Nothing is assigned:
a Market Intelligence agent and a Strategy agent see the same list and may
choose differently, and the record will say which of them chose well.

**What do you think, and how sure are you?** Shown the recent bars of the
instrument it chose, the agent replies in a fixed form: a horizon from a closed
set, a direction, a confidence, a thesis in its own words, and what would make
it wrong. The prose is held to the figure rule — every numeral must appear in
the material — and the confidence is the one number it is allowed to invent,
because inventing it is the job.

Then the seat seals it. The reference close, the instant it resolves and every
word are hashed, and the row is written. Three refusals hold the seat shut:

* an unreadable reply seals nothing — a parse that guessed would put the
  parser's view on the agent's record;
* a figure nobody showed the agent seals nothing — a thesis reasoned from an
  invented number is not a thesis about the market;
* a horizon that has already passed at the moment of sealing seals nothing —
  the one way a "forward" prediction can quietly be a backward one.

What the seat does not do is as deliberate as what it does. It does not fetch.
It shows the agent a recording and says when it was made, and if the recording
is stale enough that the horizon has already expired, the agent gets no thesis
rather than a contaminated one.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.decide import NOTHING, Choice, Question, UndecidableAnswer, decide_as
from aurelis.agents.interpret import (
    FIGURE_RULE,
    UnsourcedFigures,
    allowed_figures,
    render_material,
    unsourced_numerals,
)
from aurelis.core.canonical import sha256_of
from aurelis.core.clock import Clock, SystemClock, isoformat
from aurelis.core.enums import Actor, EventKind, ModelTier
from aurelis.core.ids import RefKind, uuid7
from aurelis.intel.live import interval_seconds
from aurelis.intel.snapshots import MarketSnapshot, SnapshotBar
from aurelis.judgement.adversary import Adversary, respond
from aurelis.judgement.tables import Thesis
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.llm.routing import model_for
from aurelis.platform.llm.types import LlmRequest, Message, ModelRef

__all__ = [
    "CRITIC_CHARTERS",
    "HORIZONS",
    "SYSTEM",
    "JudgementRefused",
    "Resolvable",
    "SealedThesis",
    "Seat",
    "View",
    "parse_view",
    "resolvable",
    "seat_agent",
    "seal_of",
    "verify_seal",
    "view_question",
]

SYSTEM = (
    "You are an analyst at a research company that is building a forward "
    "track record. You will be asked which market you want to state a view on, "
    "and then for the view itself: a direction, a horizon, and how confident "
    "you are. Your view is sealed and hashed before the outcome exists, scored "
    "mechanically when the horizon expires, and your calibration over hundreds "
    "of such calls is the measure of you -- not any single outcome.\n\n"
    "Say what you actually believe. A confidence of 0.55 that is right 55% of "
    "the time is a good record; a confidence of 0.9 that is right 60% of the "
    "time is a bad one. If you have no view, say `nothing`: abstaining is "
    "legitimate and is recorded as such. Do not state a view to seem useful."
)

HORIZONS: tuple[Choice, ...] = (
    Choice("6h", "6 hours ahead"),
    Choice("24h", "24 hours ahead"),
    Choice("72h", "72 hours ahead"),
    Choice("168h", "168 hours ahead"),
)
"""How far ahead a view may look. Closed, and not a design space.

A horizon is a resolution mechanic rather than a choice about the market: the
resolver has to know which bar settles the proposition, and a horizon that fell
between bars would be settled by whichever bar somebody picked. The set is
short at the short end on purpose — a thesis that resolves in six hours produces
a scored record in a day, which is the fastest honest evidence there is.
"""

_HOURS: dict[str, int] = {c.key: int(c.key[:-1]) for c in HORIZONS}
_LOOKBACKS: tuple[int, ...] = (6, 24, 72, 168)
_SHOWN_BARS = 24

_FIELD = re.compile(r"^\s*(HORIZON|DIRECTION|CONFIDENCE|THESIS|WRONG_IF)\s*:\s*(.*)$", re.I)


class JudgementRefused(RuntimeError):
    """The agent did not produce a thesis the seat could seal.

    Carries the stage it failed at. Nothing is written on refusal: a thesis
    half-filled by the software would be the software's view on the agent's
    record.
    """

    def __init__(self, stage: str, cause: str) -> None:
        super().__init__(f"judgement refused at {stage!r}: {cause}. Nothing was sealed.")
        self.stage = stage
        self.cause = cause


# ------------------------------------------------------------ what can be judged


@dataclass(frozen=True, slots=True)
class Resolvable:
    """An instrument the company holds a recording of, and so can score."""

    snapshot: MarketSnapshot
    closes: tuple[tuple[dt.datetime, Decimal], ...]
    """The last bars, oldest first. What the agent is shown."""

    @property
    def key(self) -> str:
        return self.snapshot.symbol.lower()

    @property
    def reference_at(self) -> dt.datetime:
        return self.closes[-1][0]

    @property
    def reference_close(self) -> Decimal:
        return self.closes[-1][1]

    def change_over(self, bars: int) -> Decimal | None:
        """Percentage change of the close over the last ``bars`` bars, or
        ``None`` when the recording is shorter than that."""
        if len(self.closes) <= bars:
            return None
        then = self.closes[-1 - bars][1]
        if not then:
            return None
        return ((self.reference_close / then - 1) * 100).quantize(Decimal("0.01"))

    def summary(self) -> str:
        parts = [f"close {self.reference_close}"]
        for bars in _LOOKBACKS:
            change = self.change_over(bars)
            if change is not None:
                parts.append(f"change over {bars} bars {change}%")
        parts.append(
            f"recorded {self.snapshot.ref} ({'market' if self.snapshot.is_live else 'fixture'})"
        )
        return ", ".join(parts)


def resolvable(session: Session, *, shown: int = 168) -> tuple[Resolvable, ...]:
    """Every instrument with a recording, newest recording per instrument.

    The option set of the first question. Not a menu of ideas — the boundary of
    what the company can check. An instrument nobody recorded has no reference
    close to seal against and no bar to settle it with.
    """
    newest: dict[str, MarketSnapshot] = {}
    rows = session.execute(
        sa.select(MarketSnapshot).order_by(
            MarketSnapshot.fetched_at.desc(), MarketSnapshot.ref.desc()
        )
    ).scalars()
    for row in rows:
        newest.setdefault(row.symbol, row)

    out: list[Resolvable] = []
    for symbol in sorted(newest):
        snapshot = newest[symbol]
        bars = session.execute(
            sa.select(SnapshotBar.timestamp, SnapshotBar.close)
            .where(SnapshotBar.snapshot_ref == snapshot.ref)
            .order_by(SnapshotBar.timestamp.desc())
            .limit(shown + 1)
        ).all()
        closes = tuple(
            (
                moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC),
                Decimal(str(close)),
            )
            for moment, close in reversed(bars)
        )
        if closes:
            out.append(Resolvable(snapshot, closes))
    return tuple(out)


# ------------------------------------------------------------ the second question


@dataclass(frozen=True, slots=True)
class View:
    """What the agent said, parsed and not interpreted."""

    horizon: str
    direction: str
    confidence: Decimal
    thesis: str
    wrong_if: str

    @property
    def declined(self) -> bool:
        return self.direction == NOTHING

    @property
    def hours(self) -> int:
        return _HOURS[self.horizon]

    @property
    def probability_up(self) -> Decimal:
        return self.confidence if self.direction == "up" else Decimal(1) - self.confidence


def view_question(instrument: str) -> str:
    horizons = "\n".join(c.render() for c in HORIZONS)
    return (
        f"State your view on {instrument}, or decline.\n\n"
        f"Horizons:\n{horizons}\n\n"
        "Reply in exactly this form and nothing else:\n"
        "HORIZON: <one of the horizon keys>\n"
        "DIRECTION: up | down | nothing\n"
        "CONFIDENCE: <a probability strictly above 0.5 and at most 1, that the "
        "close at the horizon is on the side you named>\n"
        "THESIS: <why, in one to three sentences>\n"
        "WRONG_IF: <what would make this wrong, in one sentence>\n\n"
        "`DIRECTION: nothing` means you have no view; the other lines may then "
        "be empty. Do not restate your confidence inside THESIS or WRONG_IF.\n\n"
        f"{FIGURE_RULE}"
    )


def parse_view(text: str) -> View:
    """Pull the five fields out of a reply, or refuse.

    Strict on purpose. ``CONFIDENCE`` is the one number the agent is allowed to
    invent, and it is parsed here rather than figure-checked; the prose is
    checked by the caller against what the agent was shown.
    """
    fields: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).upper()
            fields[current] = match.group(2).strip()
        elif current in ("THESIS", "WRONG_IF") and line.strip():
            fields[current] = f"{fields[current]} {line.strip()}".strip()

    direction = fields.get("DIRECTION", "").strip().lower()
    if direction == NOTHING:
        return View(NOTHING, NOTHING, Decimal("1"), "", "")
    if direction not in ("up", "down"):
        raise JudgementRefused(
            "direction", f"got {direction or '<empty>'!r}, expected up, down or {NOTHING}"
        )

    horizon = fields.get("HORIZON", "").strip().lower()
    if horizon not in _HOURS:
        raise JudgementRefused(
            "horizon", f"got {horizon or '<empty>'!r}, expected one of {list(_HOURS)}"
        )

    raw = fields.get("CONFIDENCE", "").strip().rstrip("%")
    try:
        confidence = Decimal(raw)
    except InvalidOperation:
        raise JudgementRefused("confidence", f"{raw or '<empty>'!r} is not a number") from None
    if confidence > 1 and confidence <= 100:
        confidence = confidence / 100
    if not Decimal("0.5") < confidence <= 1:
        raise JudgementRefused(
            "confidence",
            f"{confidence} is not strictly above 0.5 and at most 1. A view held "
            "at exactly even odds is not a view; say nothing instead",
        )

    thesis = fields.get("THESIS", "").strip()
    wrong_if = fields.get("WRONG_IF", "").strip()
    if len(thesis) <= 20:
        raise JudgementRefused("thesis", "a thesis of fewer than twenty characters is not one")
    if len(wrong_if) <= 10:
        raise JudgementRefused(
            "wrong_if", "a view whose holder cannot say what would make it wrong is unfalsifiable"
        )
    return View(horizon, direction, confidence.quantize(Decimal("0.01")), thesis, wrong_if)


# ------------------------------------------------------------ the seal


@dataclass(frozen=True, slots=True)
class SealedThesis:
    """What was sealed, and what it cost."""

    ref: str
    agent_ref: str
    instrument: str
    horizon_hours: int
    direction: str
    confidence: Decimal
    reference_close: Decimal
    reference_at: dt.datetime
    resolves_at: dt.datetime
    sealed_at: dt.datetime
    seal: str
    thesis: str
    wrong_if: str
    is_live: bool
    model: str
    calls: int
    critic_ref: str | None = None
    attack_verdict: str | None = None
    attack: str | None = None
    confidence_stated: Decimal | None = None
    response: str | None = None

    def describe(self) -> str:
        return (
            f"{self.ref} {self.agent_ref}: {self.instrument} {self.direction} "
            f"over {self.horizon_hours}h at {self.confidence}, reference "
            f"{self.reference_close}, resolves {self.resolves_at:%Y-%m-%d %H:%M}Z"
        )


_MONEY_Q = Decimal("0.00000001")


def _money(value: Any) -> str:
    """A Money-typed value as it is stored, so the seal survives a round-trip.

    ``confidence`` is set as ``Decimal("0.65")`` and read back from SQLite as
    ``Decimal("0.65000000")`` -- the eight-place scale the Money type stores.
    Hashing ``str()`` of the two gives different digests and ``verify_seal``
    then fails on every row it reads back. The seal is computed over the stored
    form on both sides.
    """
    return str(Decimal(str(value)).quantize(_MONEY_Q))


def seal_of(row: Thesis) -> str:
    """The hash over everything fixed at sealing."""
    return sha256_of(
        {
            "ref": row.ref,
            "agent": row.agent_ref,
            "desk": row.desk,
            "instrument": row.instrument,
            "interval": row.interval,
            "horizon_hours": row.horizon_hours,
            "snapshot": row.snapshot_ref,
            "reference_at": isoformat(row.reference_at),
            "reference_close": row.reference_close,
            "resolves_at": isoformat(row.resolves_at),
            "is_live": row.is_live,
            "direction": row.direction,
            "confidence": _money(row.confidence),
            "probability_up": _money(row.probability_up),
            "thesis": row.thesis,
            "wrong_if": row.wrong_if,
            "material": row.material_digest,
            "model": row.model,
            "critic": row.critic_ref or "",
            "attack_verdict": row.attack_verdict or "",
            "attack": row.attack or "",
            "confidence_stated": _money(row.confidence_stated)
            if row.confidence_stated is not None
            else "",
            "response": row.response or "",
            "response_because": row.response_because or "",
            "sealed_at": isoformat(row.sealed_at),
        }
    )


def verify_seal(row: Thesis) -> bool:
    return seal_of(row) == row.seal


# ------------------------------------------------------------ the seat


class Seat:
    """Put one agent through the two questions and seal what it says."""

    __slots__ = ("_adversary", "_artifacts", "_clock", "_ledger", "_provider")

    def __init__(
        self,
        provider: Any,
        artifacts: Any,
        ledger: Any,
        clock: Clock | None = None,
        *,
        adversary: Adversary | None = None,
    ) -> None:
        self._provider = provider
        self._artifacts = artifacts
        self._ledger = ledger
        self._clock = clock or SystemClock()
        self._adversary = adversary
        """Who attacks a view before it is sealed. ``None`` seals unattacked
        and the row says so; a critic who is also the author is not an
        adversary and is ignored."""

    def judge(
        self,
        session: Session,
        *,
        agent_ref: str,
        tier: ModelTier = ModelTier.MID,
        task_ref: str | None = None,
        at: dt.datetime | None = None,
        exclude: frozenset[str] = frozenset(),
        identity: str = "",
    ) -> SealedThesis | None:
        """Ask, ask again, seal. ``None`` means the agent declined.

        ``exclude`` names instruments this agent already holds an open thesis
        on. They are not offered: a second view on the same instrument before
        the first resolved would be the same bet placed twice, and it would
        count twice in the calibration.

        ``identity`` is who is sitting: handle, department, charters. It goes
        into the system prompt, and it is not decoration. The first test of
        two agents in this seat had them shown identical material, and the
        response cache -- which ignores who asked, correctly, for identical
        questions -- handed the second agent the first one's answer. A society
        whose members are the same prompt with different names is one agent.
        """
        moment = at or self._clock.now()
        system = f"{SYSTEM}\n\n{identity}" if identity else SYSTEM
        candidates = tuple(r for r in resolvable(session) if r.snapshot.symbol not in exclude)
        if not candidates:
            raise JudgementRefused(
                "market",
                "nothing can be resolved: no recording exists that this agent "
                "does not already hold an open view on. A prediction nobody can "
                "check is not a prediction",
            )

        record = _own_record(session, agent_ref)
        choose_material: dict[str, Any] = {
            "now": isoformat(moment),
            "markets": {r.snapshot.symbol: r.summary() for r in candidates},
            "your_record": record,
        }
        question = Question(
            prompt="Which market do you want to state a view on?",
            options=tuple(Choice(r.key, r.summary()) for r in candidates),
            multiple=False,
        )
        try:
            chosen = decide_as(
                self._provider,
                session,
                agent_ref=agent_ref,
                question=question,
                material=choose_material,
                system=system,
                tier=tier,
                task_ref=task_ref,
            )
        except (UndecidableAnswer, UnsourcedFigures) as error:
            raise JudgementRefused("market", str(error)) from error

        if chosen.abstained:
            self._declined(session, agent_ref, "market", chosen.reasoning, moment)
            return None
        picked = next(r for r in candidates if r.key in chosen.chosen)

        # -------------------------------------------------- the view itself
        material = _view_material(picked, moment, record)
        rendered = f"{render_material(material)}\n\n{view_question(picked.snapshot.symbol)}"
        model_id = model_for(self._provider.name, tier)
        response = self._provider.complete(
            session,
            LlmRequest(
                model=ModelRef(
                    provider=self._provider.name, model=model_id, tier=tier, max_tokens=500
                ),
                system=system,
                messages=(Message("user", rendered),),
                actor=agent_ref,
                task_ref=task_ref,
            ),
        )
        try:
            view = parse_view(response.text)
        except JudgementRefused:
            raise

        if view.declined:
            self._declined(session, agent_ref, picked.snapshot.symbol, "", moment)
            return None

        permitted = allowed_figures(material, {"question": view_question(picked.snapshot.symbol)})
        invented = unsourced_numerals(f"{view.thesis}\n{view.wrong_if}", permitted)
        if invented:
            cause = (
                f"the thesis cites {len(invented)} figure(s) the agent was not "
                f"shown: {', '.join(invented[:5])}"
            )
            raise JudgementRefused("figures", cause)

        resolves_at = picked.reference_at + dt.timedelta(hours=view.hours)
        if resolves_at <= moment:
            cause = (
                f"the recording ends at {isoformat(picked.reference_at)} and a "
                f"{view.hours}h horizon from there is {isoformat(resolves_at)}, "
                f"which has already passed at {isoformat(moment)}. A view on an "
                "outcome that already exists is not forward"
            )
            raise JudgementRefused("forward", cause)

        # -------------------------------------------------- the attack
        attack = None
        answer = None
        confidence = view.confidence
        calls = 2
        instrument = picked.snapshot.symbol
        if self._adversary is not None and self._adversary.critic_ref != agent_ref:
            attack = self._adversary.attack(
                session, material=material, view=view, instrument=instrument, task_ref=task_ref
            )
            calls += 1
            if not attack.unreadable:
                answer = respond(
                    self._provider,
                    session,
                    agent_ref=agent_ref,
                    system=system,
                    tier=tier,
                    material=material,
                    view=view,
                    instrument=instrument,
                    attack=attack,
                    task_ref=task_ref,
                )
                calls += 1
                if answer.kind == "withdraw":
                    self._declined(
                        session,
                        agent_ref,
                        instrument,
                        answer.because,
                        moment,
                        extra={
                            "withdrawn_after_attack": True,
                            "critic": attack.critic_ref,
                            "attack_verdict": attack.verdict,
                            "attack": attack.text[:300],
                            "confidence_stated": str(view.confidence),
                        },
                    )
                    return None
                if answer.confidence is not None:
                    confidence = answer.confidence
        probability_up = confidence if view.direction == "up" else Decimal(1) - confidence

        shown = self._artifacts.put_json(
            session,
            {
                "choose": choose_material,
                "view": material,
                "reply": response.text,
                "attack": None if attack is None else attack.text,
                "response": None if answer is None else answer.because,
            },
            kind="judgement.material",
            produced_by=agent_ref,
            actor=agent_ref,
        )
        spend_tokens = chosen.spend.tokens + response.usage.total
        spend_usd = chosen.spend.usd + response.usd
        if attack is not None:
            spend_tokens += attack.tokens
            spend_usd += attack.usd
        if answer is not None:
            spend_tokens += answer.tokens
            spend_usd += answer.usd
        model_label = f"{self._provider.name}:{model_id}"

        ref = allocate_ref(session, RefKind.THESIS)
        row = Thesis(
            thesis_id=uuid7(),
            ref=ref,
            agent_ref=agent_ref,
            desk=picked.snapshot.desk,
            instrument=picked.snapshot.symbol,
            interval=picked.snapshot.interval,
            horizon_hours=view.hours,
            snapshot_ref=picked.snapshot.ref,
            reference_at=picked.reference_at,
            reference_close=str(picked.reference_close),
            resolves_at=resolves_at,
            is_live=bool(picked.snapshot.is_live),
            direction=view.direction,
            confidence=confidence,
            probability_up=probability_up,
            thesis=view.thesis,
            wrong_if=view.wrong_if,
            material_digest=shown.digest,
            model=model_label,
            tokens=spend_tokens,
            usd=spend_usd,
            critic_ref=None if attack is None else attack.critic_ref,
            attack_verdict=None if attack is None else attack.verdict,
            attack=None if attack is None else attack.text,
            confidence_stated=None if attack is None else view.confidence,
            response=None if answer is None else answer.kind,
            response_because=None if answer is None else answer.because,
            sealed_at=moment,
            seal="0" * 64,
        )
        row.seal = seal_of(row)
        session.add(row)
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.THESIS_SEALED,
            actor=agent_ref,
            subject=ref,
            payload={
                "instrument": row.instrument,
                "horizon_hours": row.horizon_hours,
                "direction": row.direction,
                "confidence": str(row.confidence),
                "reference_close": row.reference_close,
                "reference_at": isoformat(row.reference_at),
                "resolves_at": isoformat(row.resolves_at),
                "snapshot": row.snapshot_ref,
                "is_live": row.is_live,
                "material": shown.digest[:16],
                "seal": row.seal[:16],
                "model": model_label,
                "attacked_by": row.critic_ref,
                "attack_verdict": row.attack_verdict,
                "confidence_stated": None
                if row.confidence_stated is None
                else str(row.confidence_stated),
                "response": row.response,
            },
            at=moment,
        )
        return SealedThesis(
            ref=ref,
            agent_ref=agent_ref,
            instrument=row.instrument,
            horizon_hours=row.horizon_hours,
            direction=row.direction,
            confidence=row.confidence,
            reference_close=picked.reference_close,
            reference_at=row.reference_at,
            resolves_at=row.resolves_at,
            sealed_at=moment,
            seal=row.seal,
            thesis=row.thesis,
            wrong_if=row.wrong_if,
            is_live=row.is_live,
            model=model_label,
            calls=calls,
            critic_ref=row.critic_ref,
            attack_verdict=row.attack_verdict,
            attack=row.attack,
            confidence_stated=row.confidence_stated,
            response=row.response,
        )

    def _declined(
        self,
        session: Session,
        agent_ref: str,
        at_stage: str,
        why: str,
        moment: dt.datetime,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._ledger.append(
            session,
            kind=EventKind.THESIS_DECLINED,
            actor=agent_ref,
            subject=agent_ref,
            payload={"stage": at_stage, "reasoning": why[:300], **(extra or {})},
            at=moment,
        )


def _own_record(session: Session, agent_ref: str) -> dict[str, Any]:
    """What this agent has said before, and how it went. Its memory."""
    from aurelis.judgement.calibration import agent_calibration

    record = agent_calibration(session, agent_ref, live_only=False)
    recent = session.execute(
        sa.select(Thesis)
        .where(Thesis.agent_ref == agent_ref, Thesis.scored_at.is_not(None))
        .order_by(Thesis.scored_at.desc())
        .limit(5)
    ).scalars()
    lines = [
        f"{t.instrument} {t.direction} over {t.horizon_hours} bars at {t.confidence}: "
        f"{'right' if _hit(t) else 'wrong'}"
        for t in recent
    ]
    out: dict[str, Any] = {
        "sealed": record.sealed,
        "scored": record.scored,
        "mean_brier": str(record.mean_brier) if record.mean_brier is not None else "none yet",
        "coin_toss_brier": "0.25",
    }
    if lines:
        out["most_recent_scored"] = "; ".join(lines)
    return out


def _hit(row: Thesis) -> bool:
    return bool(row.outcome) == (row.direction == "up")


def _view_material(
    picked: Resolvable, moment: dt.datetime, record: dict[str, Any]
) -> dict[str, Any]:
    step = interval_seconds(picked.snapshot.interval)
    return {
        "instrument": {
            "symbol": picked.snapshot.symbol,
            "desk": picked.snapshot.desk,
            "bar interval": picked.snapshot.interval,
            "data": (
                f"recorded market data, {picked.snapshot.ref}"
                if picked.snapshot.is_live
                else f"a fixture, {picked.snapshot.ref} -- not a market"
            ),
            "reference close": str(picked.reference_close),
            "reference bar opened": isoformat(picked.reference_at),
            "now": isoformat(moment),
            "age of reference": (
                f"{int((moment - picked.reference_at).total_seconds() // step)} bars"
            ),
        },
        "recent_closes": [
            f"{isoformat(when)} {close}" for when, close in picked.closes[-_SHOWN_BARS:]
        ],
        "changes": {
            f"over {bars} bars": f"{change}%"
            for bars in _LOOKBACKS
            if (change := picked.change_over(bars)) is not None
        },
        "your_record": record,
    }


def seat_agent(
    runtime: Any,
    *,
    agent_handle: str,
    at: dt.datetime | None = None,
) -> SealedThesis | None:
    """Put a named agent in the seat, under a task, and return what it sealed.

    Wraps :meth:`Seat.judge` with the queue and the roster so the cost of the
    judgement joins to the agent and the task, exactly as an authoring does.
    Raises :class:`JudgementRefused`; returns ``None`` on a decline.
    """
    moment = at or runtime.clock.now()
    with runtime.database.session() as session:
        seated = runtime.roster.by_handle(session, agent_handle)
        open_on = frozenset(
            session.execute(
                sa.select(Thesis.instrument).where(
                    Thesis.agent_ref == seated.ref, Thesis.scored_at.is_(None)
                )
            ).scalars()
        )
        task = runtime.queue.enqueue(
            session,
            kind="judgement.thesis",
            assignee=seated.ref,
            payload={"agent": seated.handle},
            actor=Actor.SYSTEM,
            at=moment,
        )
        claimed = runtime.queue.claim(session, worker=seated.ref, at=moment)
        task_ref = claimed.ref if claimed is not None else task.ref
        critic = critic_for(runtime, session, author_ref=seated.ref)
        adversary = (
            None
            if critic is None
            else Adversary(
                runtime.provider,
                critic_ref=critic.ref,
                identity=identity_of(critic),
                tier=critic.authority.tier
                if critic.authority.tier is not ModelTier.NONE
                else ModelTier.MID,
            )
        )
        seat = Seat(
            runtime.provider,
            runtime.artifacts,
            runtime.ledger,
            clock=runtime.clock,
            adversary=adversary,
        )
        refusal: JudgementRefused | None = None
        try:
            sealed = seat.judge(
                session,
                agent_ref=seated.ref,
                tier=seated.authority.tier
                if seated.authority.tier is not ModelTier.NONE
                else ModelTier.MID,
                task_ref=task_ref,
                at=moment,
                exclude=open_on,
                identity=identity_of(seated),
            )
        except JudgementRefused as error:
            if claimed is not None:
                runtime.queue.fail(session, claimed, error=str(error)[:200], at=moment)
            refusal = error
        else:
            refusal = None
        if refusal is None and claimed is not None:
            runtime.queue.succeed(
                session,
                claimed,
                result_digest=sealed.seal if sealed is not None else sha256_of({"declined": True}),
                at=moment,
            )
    if refusal is not None:
        # The failing judgement rolled its own session back, taking any event
        # written inside it. The refusal is a fact about the agent and belongs
        # on the record, so it is appended in a transaction that commits.
        with runtime.database.session() as session:
            runtime.ledger.append(
                session,
                kind=EventKind.THESIS_REFUSED,
                actor=seated.ref,
                subject=seated.ref,
                payload={"stage": refusal.stage, "cause": refusal.cause[:300]},
                at=moment,
            )
        raise refusal
    return sealed


CRITIC_CHARTERS: tuple[str, ...] = ("strategy.critic", "strategy.adversarial")


def critic_for(runtime: Any, session: Session, *, author_ref: str) -> Any | None:
    """The agent who attacks this author's view: a critic who is not the author.

    First active holder of a critic or adversarial charter by ref. ``None``
    when nobody qualifies, in which case the view is sealed unattacked and the
    row says so rather than pretending a review happened.
    """
    from aurelis.agents.tables import AgentState

    for agent in runtime.roster.all(session):
        if agent.ref == author_ref:
            continue
        if agent.state not in (AgentState.ACTIVE, AgentState.WORKING):
            continue
        if any(held in CRITIC_CHARTERS for held in agent.coverage):
            return agent
    return None


def identity_of(seated: Any) -> str:
    """Who is sitting, for the system prompt: handle, department, charters."""
    from aurelis.org.registry import charter

    titles = sorted({charter(held).name for held in seated.coverage})
    desk = f" on the {seated.desk.value} desk" if seated.desk is not None else ""
    return (
        f"You are {seated.handle} ({seated.ref}), {seated.department.value.replace('_', ' ')}"
        f"{desk}. Your charters: {', '.join(titles) or 'none'}. Read the material "
        "through that specialism; it is why you and not somebody else are being asked."
    )


def theses_of(
    session: Session, agent_ref: str | None = None, *, open_only: bool = False
) -> list[Thesis]:
    query = sa.select(Thesis).order_by(Thesis.sealed_at.desc(), Thesis.ref.desc())
    if agent_ref is not None:
        query = query.where(Thesis.agent_ref == agent_ref)
    if open_only:
        query = query.where(Thesis.scored_at.is_(None))
    return list(session.execute(query).scalars())
