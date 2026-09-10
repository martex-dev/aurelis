"""Calibration: the measure of an agent, read off its sealed record.

Everything here is arithmetic over rows, with no model in the loop. Three
numbers matter and they are reported together, because any one of them alone
can be gamed.

**Mean Brier.** ``(p - outcome)^2`` averaged. Always saying 50% scores 0.25,
so an agent at 0.25 is not calibrated, it is abstaining in numeric form.

**Hit rate against stated confidence, by band.** An agent at 70% confidence
should be right about 70% of the time. The bands make over-confidence visible
as a gap between what was said and what happened, which a single mean hides.

**The base rate.** If an instrument went up 70% of the time, an agent that
always said "up at 70%" would look calibrated and know nothing. The report
carries the Brier score that always predicting the observed up-frequency would
have earned, so a record can be read against the market it was made on rather
than against a coin.

A record over fixture data is reported separately from one over a market. A
fixture is a random walk; being calibrated on it is being calibrated on
nothing, and the mandate reads only the market rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.judgement.tables import Thesis

__all__ = [
    "BANDS",
    "COIN_TOSS",
    "AgentCalibration",
    "Band",
    "CriticRecord",
    "agent_calibration",
    "calibration_over",
    "company_calibration",
    "critic_record",
    "critics_over",
]

COIN_TOSS = Decimal("0.25")
"""The Brier score of always saying 50%. The bar a record must beat to be
saying anything at all."""

BANDS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0.5"), Decimal("0.6")),
    (Decimal("0.6"), Decimal("0.7")),
    (Decimal("0.7"), Decimal("0.8")),
    (Decimal("0.8"), Decimal("0.9")),
    (Decimal("0.9"), Decimal("1.0")),
)
"""Confidence bands, lower inclusive, upper exclusive except the last."""

_Q = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class Band:
    low: Decimal
    high: Decimal
    n: int
    stated: Decimal | None
    """Mean confidence the agent stated inside the band."""

    observed: Decimal | None
    """Fraction of the time it was right. Calibrated means ``observed ≈ stated``."""

    @property
    def gap(self) -> Decimal | None:
        if self.stated is None or self.observed is None:
            return None
        return (self.stated - self.observed).quantize(_Q)

    def describe(self) -> str:
        label = f"{self.low}-{self.high}"
        if not self.n:
            return f"{label}: no views"
        return (
            f"{label}: {self.n} view(s), said {self.stated}, right {self.observed}, "
            f"over-confident by {self.gap}"
        )


@dataclass(frozen=True, slots=True)
class AgentCalibration:
    """One record, read whole."""

    label: str
    sealed: int
    scored: int
    pending: int
    hits: int
    mean_brier: Decimal | None
    base_rate_brier: Decimal | None
    """What always predicting the observed up-frequency would have scored."""

    up_frequency: Decimal | None
    bands: tuple[Band, ...]

    @property
    def hit_rate(self) -> Decimal | None:
        if not self.scored:
            return None
        return (Decimal(self.hits) / Decimal(self.scored)).quantize(_Q)

    @property
    def informative(self) -> bool:
        """Better than a coin toss. Necessary, and nowhere near sufficient."""
        return self.mean_brier is not None and self.mean_brier < COIN_TOSS

    @property
    def beats_base_rate(self) -> bool:
        """Better than knowing only how often the instrument went up."""
        return (
            self.mean_brier is not None
            and self.base_rate_brier is not None
            and self.mean_brier < self.base_rate_brier
        )

    def describe(self) -> str:
        if not self.scored:
            return f"{self.label}: {self.sealed} sealed, none scored yet ({self.pending} pending)"
        verdict = (
            "beats the base rate"
            if self.beats_base_rate
            else (
                "beats a coin toss, not the base rate"
                if self.informative
                else "no better than a coin toss"
            )
        )
        return (
            f"{self.label}: Brier {self.mean_brier} over {self.scored} scored "
            f"({self.pending} pending), right {self.hit_rate}, base rate "
            f"{self.base_rate_brier} — {verdict}"
        )


def calibration_over(label: str, rows: Iterable[Thesis]) -> AgentCalibration:
    """Pure: the same numbers whoever supplies the rows."""
    theses = list(rows)
    scored = [t for t in theses if t.scored_at is not None and t.brier is not None]
    pending = len(theses) - len(scored)
    hits = sum(1 for t in scored if bool(t.outcome) == (t.direction == "up"))

    mean_brier: Decimal | None = None
    base_rate: Decimal | None = None
    up_frequency: Decimal | None = None
    if scored:
        total = sum((Decimal(str(t.brier)) for t in scored), Decimal(0))
        mean_brier = (total / len(scored)).quantize(_Q)
        ups = sum(1 for t in scored if t.outcome)
        up_frequency = (Decimal(ups) / len(scored)).quantize(_Q)
        base_total = sum(
            ((up_frequency - (Decimal(1) if t.outcome else Decimal(0))) ** 2 for t in scored),
            Decimal(0),
        )
        base_rate = (base_total / len(scored)).quantize(_Q)

    bands: list[Band] = []
    for low, high in BANDS:
        inside = [
            t
            for t in scored
            if low <= Decimal(str(t.confidence)) < high
            or (high == Decimal("1.0") and Decimal(str(t.confidence)) == high)
        ]
        if not inside:
            bands.append(Band(low, high, 0, None, None))
            continue
        stated = (
            sum((Decimal(str(t.confidence)) for t in inside), Decimal(0)) / len(inside)
        ).quantize(_Q)
        right = sum(1 for t in inside if bool(t.outcome) == (t.direction == "up"))
        observed = (Decimal(right) / len(inside)).quantize(_Q)
        bands.append(Band(low, high, len(inside), stated, observed))

    return AgentCalibration(
        label=label,
        sealed=len(theses),
        scored=len(scored),
        pending=pending,
        hits=hits,
        mean_brier=mean_brier,
        base_rate_brier=base_rate,
        up_frequency=up_frequency,
        bands=tuple(bands),
    )


@dataclass(frozen=True, slots=True)
class CriticRecord:
    """A critic's record: did its verdicts predict failure?"""

    label: str
    attacks: int
    scored: int
    broken: int
    caught: int
    """``broken`` on a view that turned out wrong."""

    false_alarms: int
    """``broken`` on a view that turned out right."""

    missed: int
    """``stands`` on a view that turned out wrong."""

    moved: int
    """Views whose author revised after the attack. Withdrawals never become
    rows and are counted on the ledger, not here."""

    @property
    def precision(self) -> Decimal | None:
        """Of the views it called broken, how many were."""
        scored_broken = self.caught + self.false_alarms
        if not scored_broken:
            return None
        return (Decimal(self.caught) / Decimal(scored_broken)).quantize(_Q)

    @property
    def catch_rate(self) -> Decimal | None:
        """Of the views that turned out wrong, how many it called broken."""
        wrong = self.caught + self.missed
        if not wrong:
            return None
        return (Decimal(self.caught) / Decimal(wrong)).quantize(_Q)

    def describe(self) -> str:
        if not self.scored:
            return f"{self.label}: {self.attacks} attack(s), none scored yet"
        return (
            f"{self.label}: {self.attacks} attack(s), {self.broken} broken; of the scored, "
            f"caught {self.caught}, false alarms {self.false_alarms}, missed {self.missed} "
            f"(precision {self.precision}, catch rate {self.catch_rate}); moved {self.moved}"
        )


def critics_over(label: str, rows: Iterable[Thesis]) -> CriticRecord:
    theses = [t for t in rows if t.critic_ref is not None and t.attack_verdict != "unreadable"]
    scored = [t for t in theses if t.scored_at is not None]
    hit = {t.ref: bool(t.outcome) == (t.direction == "up") for t in scored}
    caught = sum(1 for t in scored if t.attack_verdict == "broken" and not hit[t.ref])
    alarms = sum(1 for t in scored if t.attack_verdict == "broken" and hit[t.ref])
    missed = sum(1 for t in scored if t.attack_verdict == "stands" and not hit[t.ref])
    return CriticRecord(
        label=label,
        attacks=len(theses),
        scored=len(scored),
        broken=sum(1 for t in theses if t.attack_verdict == "broken"),
        caught=caught,
        false_alarms=alarms,
        missed=missed,
        moved=sum(1 for t in theses if t.response == "revise"),
    )


def critic_record(session: Session, critic_ref: str, *, live_only: bool = True) -> CriticRecord:
    return critics_over(
        critic_ref, _rows(session, Thesis.critic_ref == critic_ref, live_only=live_only)
    )


def _rows(
    session: Session, *where: sa.ColumnElement[bool], live_only: bool
) -> list[Thesis]:
    query = sa.select(Thesis)
    for clause in where:
        query = query.where(clause)
    if live_only:
        query = query.where(Thesis.is_live.is_(True))
    # A mechanism firing carries its proposer as agent_ref but is not that
    # agent judging; it belongs to the mechanism record, not the forward
    # calibration the mandate and the agent pages read.
    query = query.where(Thesis.mechanism_ref.is_(None))
    return list(session.execute(query.order_by(Thesis.sealed_at)).scalars())


def agent_calibration(
    session: Session, agent_ref: str, *, live_only: bool = True
) -> AgentCalibration:
    return calibration_over(
        agent_ref, _rows(session, Thesis.agent_ref == agent_ref, live_only=live_only)
    )


def company_calibration(
    session: Session, *, live_only: bool = True
) -> dict[str, list[AgentCalibration]]:
    """The whole record, cut four ways: overall, by agent, by instrument, by horizon."""
    rows = _rows(session, live_only=live_only)
    by_agent: dict[str, list[Thesis]] = {}
    by_instrument: dict[str, list[Thesis]] = {}
    by_horizon: dict[str, list[Thesis]] = {}
    for row in rows:
        by_agent.setdefault(row.agent_ref, []).append(row)
        by_instrument.setdefault(row.instrument, []).append(row)
        by_horizon.setdefault(f"{row.horizon_hours}h", []).append(row)
    by_critic: dict[str, list[Thesis]] = {}
    for row in rows:
        if row.critic_ref is not None:
            by_critic.setdefault(row.critic_ref, []).append(row)
    return {
        "critics": [critics_over(k, v) for k, v in sorted(by_critic.items())],  # type: ignore[misc]
        "overall": [calibration_over("company", rows)],
        "by_agent": [calibration_over(k, v) for k, v in sorted(by_agent.items())],
        "by_instrument": [calibration_over(k, v) for k, v in sorted(by_instrument.items())],
        "by_horizon": [
            calibration_over(k, v)
            for k, v in sorted(by_horizon.items(), key=lambda kv: int(kv[0][:-1]))
        ],
    }
