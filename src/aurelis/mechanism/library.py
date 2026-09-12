"""Stating a mechanism, sealing it, and reading its out-of-sample record."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import sha256_of
from aurelis.core.clock import Clock, SystemClock, isoformat
from aurelis.core.enums import Actor, EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.judgement.calibration import COIN_TOSS, AgentCalibration, calibration_over
from aurelis.judgement.tables import Thesis
from aurelis.mechanism.tables import Mechanism
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["MIN_SCORED_PREDICTIONS", "MechanismStatus", "Mechanisms", "seal_of"]

MIN_SCORED_PREDICTIONS = 20
"""How many scored out-of-sample predictions a mechanism needs before its
record is read as evidence rather than as a handful of coin flips."""


def _unconditional_base_rate(session: Session, scored: list[Thesis]) -> Decimal | None:
    """Brier of always predicting the instrument's own up-frequency.

    For each scored prediction, the up-frequency is read from the newest
    recording of its instrument over its horizon: the fraction of bars whose
    close ``h`` bars later was above their own close. What a forecaster who
    knew only the drift would have said, scored against what happened.
    """
    from aurelis.intel.snapshots import MarketSnapshot, Snapshots

    if not scored:
        return None
    frequencies: dict[tuple[str, int], Decimal] = {}
    total = Decimal(0)
    for thesis in scored:
        key = (thesis.instrument, thesis.horizon_hours)
        if key not in frequencies:
            snapshot = (
                session.execute(
                    sa.select(MarketSnapshot)
                    .where(MarketSnapshot.symbol == thesis.instrument)
                    .order_by(MarketSnapshot.bars.desc(), MarketSnapshot.ref.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if snapshot is None:
                frequencies[key] = Decimal("0.5")
            else:
                bars = Snapshots.bars_of(session, snapshot.ref)
                horizon = thesis.horizon_hours
                ups = sum(
                    1 for i in range(len(bars) - horizon) if bars[i + horizon].close > bars[i].close
                )
                span = max(1, len(bars) - horizon)
                frequencies[key] = (Decimal(ups) / Decimal(span)).quantize(Decimal("0.0001"))
        p = frequencies[key]
        realised = Decimal(1) if thesis.outcome else Decimal(0)
        total += (p - realised) ** 2
    return (total / len(scored)).quantize(Decimal("0.0001"))


def seal_of(row: Mechanism) -> str:
    # The conjunction fields enter the seal only when set, so every mechanism
    # sealed before M38 still verifies against the digest it was given.
    conjunction = (
        {"then_kind": row.then_kind, "within_hours": row.within_hours} if row.then_kind else {}
    )
    return sha256_of(
        {
            "ref": row.ref,
            "agent": row.agent_ref,
            "title": row.title,
            "trigger_kind": row.trigger_kind,
            **conjunction,
            "desk": row.desk,
            "horizon_hours": row.horizon_hours,
            "direction": row.direction,
            "confidence": str(Decimal(str(row.confidence)).quantize(Decimal("0.00000001"))),
            "why": row.why,
            "other_side": row.other_side,
            "decay": row.decay,
            "origin": row.origin,
            "found_on_instrument": row.found_on_instrument,
            "found_on_event": row.found_on_event,
            "stated_at": isoformat(row.stated_at),
        }
    )


def verify_seal(row: Mechanism) -> bool:
    return seal_of(row) == row.seal


@dataclass(frozen=True, slots=True)
class MechanismStatus:
    """A mechanism read against its out-of-sample predictions.

    The training occurrence is excluded: a mechanism scored on the instance it
    was found on is scored on the data that suggested it, which is the
    circularity the whole design exists to break.

    ``base_rate_brier`` is the **unconditional** one: what always predicting
    the instrument's own up-frequency over the same horizon, across every bar
    of the recording, would have scored on these predictions. The up-frequency
    *among the mechanism's own predictions* is conditioned on the trigger --
    it is the signal -- and a mechanism that was right every time could never
    beat it. The first version of this used that, and a perfect mechanism read
    as worse than the base rate.
    """

    mechanism: Mechanism
    predictions: int
    scored: int
    calibration: AgentCalibration
    retired: bool
    base_rate_brier: Decimal | None = None

    @property
    def enough(self) -> bool:
        return self.scored >= MIN_SCORED_PREDICTIONS

    @property
    def is_scheme(self) -> bool:
        """Calibrated out of sample, on enough predictions, and not retired.

        Better than a coin toss *and* better than the base rate: a mechanism
        that only learned how often the instrument goes up has learned the
        drift and nothing else.
        """
        return (
            not self.retired
            and self.enough
            and self.calibration.informative
            and self.beats_base_rate
        )

    @property
    def beats_base_rate(self) -> bool:
        return (
            self.calibration.mean_brier is not None
            and self.base_rate_brier is not None
            and self.calibration.mean_brier < self.base_rate_brier
        )

    @property
    def verdict(self) -> str:
        if self.retired:
            return "retired"
        if not self.enough:
            return f"gathering ({self.scored}/{MIN_SCORED_PREDICTIONS})"
        if self.is_scheme:
            return "candidate scheme"
        if self.calibration.informative and not self.beats_base_rate:
            return "beats a coin toss, not the base rate"
        if self.calibration.informative:
            return "beats a coin toss, not the base rate"
        return "no better than a coin toss"

    def describe(self) -> str:
        return (
            f"{self.mechanism.ref} {self.mechanism.title!r}: {self.predictions} "
            f"prediction(s), {self.scored} scored, Brier "
            f"{self.calibration.mean_brier} (coin toss {COIN_TOSS}, base rate "
            f"{self.base_rate_brier}) — {self.verdict}"
        )


class Mechanisms:
    """Where a mechanism is stated, and where its record is read."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def state(
        self,
        session: Session,
        *,
        agent_ref: str,
        title: str,
        trigger_kind: str,
        desk: str,
        horizon_hours: int,
        direction: str,
        confidence: Decimal,
        why: str,
        other_side: str,
        decay: str,
        origin: str,
        found_on_instrument: str,
        found_on_event: str,
        model: str,
        tokens: int = 0,
        usd: Decimal = Decimal("0"),
        at: dt.datetime | None = None,
        evidence_digest: str = "",
        then_kind: str | None = None,
        within_hours: int | None = None,
    ) -> Mechanism:
        moment = at or self._clock.now()
        if (then_kind is None) != (within_hours is None):
            raise ValueError("a conjunction names both its second kind and its window")
        ref = allocate_ref(session, RefKind.MECHANISM)
        row = Mechanism(
            mechanism_id=uuid7(),
            ref=ref,
            agent_ref=agent_ref,
            title=title,
            trigger_kind=trigger_kind,
            then_kind=then_kind,
            within_hours=within_hours,
            desk=desk,
            horizon_hours=horizon_hours,
            direction=direction,
            confidence=confidence,
            why=why,
            other_side=other_side,
            decay=decay,
            origin=origin,
            found_on_instrument=found_on_instrument,
            found_on_event=found_on_event,
            model=model,
            tokens=tokens,
            usd=usd,
            stated_at=moment,
            seal="0" * 64,
            evidence_digest=evidence_digest or None,
        )
        row.seal = seal_of(row)
        session.add(row)
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.MECHANISM_STATED,
            actor=agent_ref,
            subject=ref,
            payload={
                "title": title,
                "trigger": trigger_kind,
                "fires_on": row.fires_on,
                "direction": direction,
                "horizon_hours": horizon_hours,
                "confidence": str(confidence),
                "origin": origin,
                "found_on": f"{found_on_instrument}@{found_on_event}",
                "evidence": evidence_digest[:16] if evidence_digest else None,
                "seal": row.seal[:16],
            },
            at=moment,
        )
        return row

    def retire(
        self,
        session: Session,
        ref: str,
        *,
        reason: str,
        at: dt.datetime | None = None,
    ) -> Mechanism:
        moment = at or self._clock.now()
        row = session.execute(sa.select(Mechanism).where(Mechanism.ref == ref)).scalar_one()
        if row.retired_at is not None:
            return row
        row.retired_at = moment
        row.retired_reason = reason
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.MECHANISM_RETIRED,
            actor=Actor.SYSTEM,
            subject=ref,
            payload={"reason": reason[:300]},
            at=moment,
        )
        return row

    @staticmethod
    def active(session: Session) -> list[Mechanism]:
        return list(
            session.execute(
                sa.select(Mechanism).where(Mechanism.retired_at.is_(None)).order_by(Mechanism.ref)
            ).scalars()
        )

    @staticmethod
    def all(session: Session) -> list[Mechanism]:
        return list(session.execute(sa.select(Mechanism).order_by(Mechanism.ref)).scalars())

    def status(self, session: Session, ref: str) -> MechanismStatus:
        row = session.execute(sa.select(Mechanism).where(Mechanism.ref == ref)).scalar_one()
        # Out-of-sample only: exclude the training occurrence, which is the
        # first prediction the mechanism generated -- on the instrument and at
        # the event it was found on.
        predictions = list(
            session.execute(
                sa.select(Thesis).where(Thesis.mechanism_ref == ref).order_by(Thesis.ref)
            ).scalars()
        )
        out_of_sample = [
            t
            for t in predictions
            if not (t.instrument == row.found_on_instrument and t.mechanism_training)
        ]
        scored = [t for t in out_of_sample if t.scored_at is not None]
        return MechanismStatus(
            mechanism=row,
            predictions=len(out_of_sample),
            scored=len(scored),
            calibration=calibration_over(ref, out_of_sample),
            retired=row.retired_at is not None,
            base_rate_brier=_unconditional_base_rate(session, scored),
        )

    def schemes(self, session: Session) -> list[MechanismStatus]:
        """The mechanisms that have earned the right to trade on paper."""
        return [s for s in self.statuses(session) if s.is_scheme]

    def statuses(self, session: Session) -> list[MechanismStatus]:
        return [self.status(session, row.ref) for row in self.all(session)]

    def sweep_retirements(
        self, session: Session, *, at: dt.datetime | None = None
    ) -> list[Mechanism]:
        """Retire mechanisms that gathered enough predictions and failed.

        A mechanism with at least :data:`MIN_SCORED_PREDICTIONS` scored
        predictions that does not beat the base rate is not a scheme, and
        leaving it active would let it keep generating predictions the company
        already knows are noise. Retired, with the reason.
        """
        retired: list[Mechanism] = []
        for status in self.statuses(session):
            if status.retired or not status.enough:
                continue
            if not status.beats_base_rate:
                retired.append(
                    self.retire(
                        session,
                        status.mechanism.ref,
                        reason=(
                            f"{status.scored} out-of-sample predictions, Brier "
                            f"{status.calibration.mean_brier} against a base rate of "
                            f"{status.base_rate_brier}: the mechanism did not "
                            "beat knowing only how often the instrument moved"
                        ),
                        at=at,
                    )
                )
        return retired
