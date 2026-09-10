"""Driving the paper cycle: the deployed rule's own book, on bars it never saw.

M9 built the chain — proposal, assessment, approval, order, fill, position,
post-trade — and M22 found that nothing drove it. This module is the driver,
and almost all of its design is about refusing to be a demonstration.

**The rule that trades is the rule that was measured.** The design is
reconstructed from the authoring attempt and checked against the digest the
attempt recorded, then rendered through the same :func:`~aurelis.authoring.design.render`
and evaluated through the same :meth:`~aurelis.engines.local.LocalEngine.weights`
the backtest used. A driver that re-implemented the signal would measure the
distance between two implementations and report it as the distance between a
claim and reality.

**The bars it trades are bars the research never read.** A replay of the
window the backtest ran on is not a forward test; it is the backtest again,
paying different fees. So a deployment's research run is required to have been
cut short of the snapshot — :class:`~aurelis.intel.snapshots.SnapshotSource`
takes an ``upto`` for exactly this — and the walk trades the tail that was left.
:func:`held_out` computes that boundary and :func:`walk` refuses when there is
nothing behind it.

**Nothing here decides anything.** Every bar produces *intents*, and an intent
is a want: the notional the rule asks for minus the notional the book already
holds. Each one goes to Risk through :class:`~aurelis.trading.cycle.PaperCycle`
and may be cut or refused. The equity curve is then derived back out of the
fills — not accumulated as the walk goes — so the number the gap is measured
from is a consequence of what the record says happened, and a bug in this
module cannot flatter it.

What that produces is one honest measurement: **what the backtest claimed,
against what the same rule earned when every order had to survive a Risk
ceiling, a spread, a fee and a size that rounds.**
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.authoring.design import Design, render
from aurelis.authoring.tables import AuthoringAttempt
from aurelis.core.errors import IntegrityViolation
from aurelis.engines.local import LocalEngine
from aurelis.engines.spec import ExperimentSpec
from aurelis.intel.snapshots import MarketSnapshot, SnapshotSource
from aurelis.portfolio.tables import Allocation, Portfolio
from aurelis.research.tables import Registration, Result
from aurelis.trading.brokers import PaperBroker
from aurelis.trading.posttrade import Gap
from aurelis.trading.states import OrderSide
from aurelis.trading.tables import Fill, Order

__all__ = [
    "HOLD_OUT",
    "Deployed",
    "Intent",
    "PaperWalk",
    "deployments",
    "held_out",
    "intents_at",
    "measure",
    "realised",
    "sleeve_curve",
    "walk",
]

HOLD_OUT = Decimal("0.30")
"""Share of a snapshot reserved from research, so paper has somewhere to go.

Not a tuning knob. It is the answer to "what would this rule have done next?",
and a company that let itself choose the fraction after seeing the result would
be choosing its out-of-sample window — which is the same defect as choosing a
universe with hindsight, one layer up.
"""

MIN_TRADE = Decimal("0.001")
"""Smallest trade worth placing, as a share of the sleeve.

A rule whose target drifts by a hundredth of a per cent should not generate an
order; the fee would exceed the exposure change. Set low enough that it never
suppresses a real rebalance and high enough that a walk does not fill the
record with dust.
"""

_QUANTUM = Decimal("0.00000001")


def held_out(total: int, fraction: Decimal = HOLD_OUT) -> int:
    """Where research must stop, so that a forward walk exists.

    Returns the number of bars research may read. The remainder is the walk,
    and both halves must be non-empty: a snapshot too short to divide cannot
    support a forward test, and saying so is better than producing one bar of
    it.
    """
    if total < 2:
        raise IntegrityViolation(
            f"{total} bar(s) cannot be split into a research window and a "
            "forward walk"
        )
    research = int(total * (Decimal(1) - fraction))
    if not 0 < research < total:
        raise IntegrityViolation(
            f"a hold-out of {fraction} leaves {research} of {total} bars for "
            "research; one of the two halves would be empty"
        )
    return research


@dataclass(frozen=True, slots=True)
class Intent:
    """What one deployed rule wants at one bar, before Risk sees it.

    ``exposure`` is the *difference* — the notional to trade — because the
    cycle sizes an order from what Risk approves, and an intent stated as the
    whole target would re-buy a position the book already holds on every bar.
    """

    version_ref: str
    symbol: str
    side: OrderSide
    exposure: Decimal
    price: Decimal
    target: Decimal
    held: Decimal

    def as_tuple(self) -> tuple[str, str, OrderSide, Decimal, Decimal]:
        return (self.version_ref, self.symbol, self.side, self.exposure, self.price)

    def describe(self) -> str:
        return (
            f"{self.version_ref} {self.side.value} {self.exposure} of "
            f"{self.symbol} at {self.price} (target {self.target}, "
            f"held {self.held})"
        )


@dataclass(frozen=True, slots=True)
class Deployed:
    """One allocated version, with the book its rule asks for at every bar."""

    version_ref: str
    desk: str
    symbol: str
    weight: Decimal
    sleeve: Decimal
    """Weight times the book's equity: the notional this version may put to
    work, and the denominator its target weights scale."""

    spec: ExperimentSpec
    path: tuple[dict[str, Decimal], ...]
    run_ref: str
    research_bars: int
    """How many bars the locked registration read. The walk starts here."""


@dataclass(frozen=True, slots=True)
class PaperWalk:
    """One forward walk, and what the book did in it."""

    portfolio_ref: str
    snapshot_ref: str
    first_bar: int
    bars: int
    turns: int
    orders: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        """Bars walked and turns taken, kept apart.

        An earlier version printed ``turns`` as "bars walked", which read as
        though the rule had wanted something on every bar it saw. Most bars
        produce no intent at all, and that is the normal case.
        """
        return (
            f"{self.bars} bar(s) of {self.snapshot_ref} walked from bar "
            f"{self.first_bar}; the rule wanted something on {self.turns} of "
            f"them, {len(self.orders)} order(s) filled, "
            f"{len(self.refused)} refused"
        )


# ---------------------------------------------------------- what is deployed


def design_of(session: Session, version_ref: str) -> tuple[Design, AuthoringAttempt]:
    """Rebuild the authored design, and prove it is the one that was measured.

    The digest check is the whole point. Everything downstream — the weights,
    the intents, the gap — is a claim about *this* rule, and a reconstruction
    that silently differed from the recorded design would produce a number
    about a strategy the company never tested.
    """
    attempt = session.execute(
        sa.select(AuthoringAttempt).where(AuthoringAttempt.version_ref == version_ref)
    ).scalar_one_or_none()
    if attempt is None:
        raise IntegrityViolation(
            f"{version_ref} was not authored through a recorded attempt, so "
            "the rule it would trade cannot be reconstructed"
        )
    design = Design(tuple((str(k), str(v)) for k, v in attempt.design.items()))
    if design.digest() != attempt.design_digest:
        raise IntegrityViolation(
            f"{attempt.ref} recorded design digest {attempt.design_digest[:16]} "
            f"and the design read back hashes to {design.digest()[:16]}. The "
            "rule that would trade is not the rule that was measured"
        )
    return design, attempt


def _research_bars(session: Session, attempt: AuthoringAttempt) -> int:
    registration = session.execute(
        sa.select(Registration).where(Registration.ref == attempt.registration_ref)
    ).scalar_one_or_none()
    if registration is None:
        raise IntegrityViolation(f"no registration {attempt.registration_ref}")
    data = registration.spec.get("data") if isinstance(registration.spec, dict) else None
    bars = data.get("bars") if isinstance(data, dict) else None
    if not isinstance(bars, int) or bars <= 0:
        raise IntegrityViolation(
            f"{registration.ref} does not state how many bars it locked, so "
            "where the research window ended is unknown"
        )
    return bars


def _locked_source(session: Session, attempt: AuthoringAttempt) -> str:
    registration = session.execute(
        sa.select(Registration).where(Registration.ref == attempt.registration_ref)
    ).scalar_one()
    data = registration.spec.get("data") if isinstance(registration.spec, dict) else {}
    return str(data.get("source", "")) if isinstance(data, dict) else ""


def deployments(
    session: Session, *, portfolio_ref: str, snapshot: MarketSnapshot
) -> tuple[Deployed, ...]:
    """Every live allocation, with its rule evaluated over the whole snapshot.

    The weight path is computed once here rather than per bar. It is a pure
    function of closes up to each bar — the engine's own, unchanged — so
    evaluating it over the full series and reading position *t-1* at bar *t*
    is the same one-bar latency the backtest applied, without re-running the
    signal three thousand times.
    """
    portfolio = session.execute(
        sa.select(Portfolio).where(Portfolio.ref == portfolio_ref)
    ).scalar_one_or_none()
    if portfolio is None:
        raise IntegrityViolation(f"no portfolio {portfolio_ref}")

    rows = list(
        session.execute(
            sa.select(Allocation).where(
                Allocation.portfolio_ref == portfolio_ref,
                Allocation.withdrawn_at.is_(None),
            )
        ).scalars()
    )
    if not rows:
        raise IntegrityViolation(
            f"{portfolio_ref} has no live allocation; there is no rule to trade"
        )

    source = SnapshotSource(session, snapshot)
    series = {snapshot.symbol: source.bars(snapshot.symbol, limit=0)}
    engine = LocalEngine(source=source)

    out: list[Deployed] = []
    for allocation in rows:
        design, attempt = design_of(session, allocation.version_ref)
        locked = _locked_source(session, attempt)
        if snapshot.ref not in locked:
            raise IntegrityViolation(
                f"{allocation.version_ref} was measured on {locked!r} and the "
                f"walk would trade {snapshot.ref}. A gap between a claim made "
                "on one dataset and a book traded on another measures the "
                "distance between the datasets"
            )
        research = _research_bars(session, attempt)
        spec = render(
            design,
            desk=attempt.desk,
            bars=research,
            interval=snapshot.interval,
            source=locked,
        )
        out.append(
            Deployed(
                version_ref=allocation.version_ref,
                desk=attempt.desk,
                symbol=snapshot.symbol,
                weight=allocation.weight,
                sleeve=(portfolio.initial_equity * allocation.weight).quantize(
                    Decimal("0.01")
                ),
                spec=spec,
                path=tuple(engine.weights(spec, series)),
                run_ref=attempt.run_ref,
                research_bars=research,
            )
        )
    return tuple(out)


# ------------------------------------------------------------- one bar's want


def _held_notional(
    session: Session, *, portfolio_ref: str, symbol: str, price: Decimal
) -> Decimal:
    from aurelis.trading.tables import Position

    position = session.get(Position, (portfolio_ref, symbol))
    return Decimal(0) if position is None else position.quantity * price


def intents_at(
    session: Session,
    deployed: tuple[Deployed, ...],
    *,
    portfolio_ref: str,
    bars: list[object],
    index: int,
) -> tuple[Intent, ...]:
    """What each rule wants at bar ``index``, net of what the book holds.

    The signal is read at ``index - 1`` and the price is bar ``index``'s open:
    the same one-bar latency :meth:`LocalEngine._simulate` applies, and the
    reason the walk is not trading on information from the bar it is pricing
    against.

    **An intent fires when the rule changes its mind, not when the mark
    moves.** The first version compared the target notional against the
    position's current market value, which drifts with the price on every
    bar — so a rule that held one position for a week produced seven trades
    and the walk turned over twelve times more than the backtest it was being
    compared against. The engine holds a target *weight* and charges only when
    the weight changes; a driver that rebalanced to constant notional would be
    running a different strategy and reporting the difference as a
    backtest-live gap.

    Entering and leaving are still triggered by the book, because a walk that
    begins with the signal already long has to buy something.
    """
    if index < 1:
        raise IntegrityViolation(
            "the first bar of a walk has no prior signal; a rule evaluated on "
            "the bar it trades has read the future"
        )
    bar = bars[index]
    price = Decimal(str(bar.open))  # type: ignore[attr-defined]
    out: list[Intent] = []
    for item in deployed:
        if index - 1 >= len(item.path):
            continue
        book = item.path[index - 1]
        before = item.path[index - 2] if index >= 2 else {}
        target_weight = book.get(item.symbol, Decimal(0))
        target = (item.sleeve * target_weight).quantize(Decimal("0.01"))
        held = _held_notional(
            session, portfolio_ref=portfolio_ref, symbol=item.symbol, price=price
        )
        changed = book != before
        opening = target != 0 and held == 0
        closing = target == 0 and held != 0
        if not (changed or opening or closing):
            continue
        delta = target - held
        if abs(delta) < item.sleeve * MIN_TRADE:
            continue
        out.append(
            Intent(
                version_ref=item.version_ref,
                symbol=item.symbol,
                side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                exposure=abs(delta).quantize(Decimal("0.01")),
                price=price,
                target=target,
                held=held.quantize(Decimal("0.01")),
            )
        )
    return tuple(out)


# ------------------------------------------------------------------ the walk


def walk(
    runtime: object,
    session: Session,
    *,
    portfolio_ref: str,
    snapshot: MarketSnapshot,
    actors: dict[str, str],
    limit: int = 0,
    at: dt.datetime | None = None,
) -> PaperWalk:
    """Trade the snapshot's held-out tail, one bar at a time.

    Each bar is one turn of :class:`~aurelis.trading.cycle.PaperCycle`: intents
    to Risk, Risk to an approval, the approval to a paper broker marked at that
    bar's own close, and the fill to the book. Nothing is accumulated here — the
    record is the only place the walk's result exists.
    """
    deployed = deployments(session, portfolio_ref=portfolio_ref, snapshot=snapshot)
    source = SnapshotSource(session, snapshot)
    bars = source.bars(snapshot.symbol, limit=0)
    start = max(item.research_bars for item in deployed)
    if start >= len(bars):
        raise IntegrityViolation(
            f"the research window read all {len(bars)} bars of {snapshot.ref}; "
            "there is nothing left to trade forward. A walk over bars the "
            "backtest already read is the backtest again, paying fees"
        )
    end = len(bars) if not limit else min(len(bars), start + limit)

    orders: list[str] = []
    refused: list[str] = []
    notes: list[str] = []
    turns = 0
    for index in range(start, end):
        bar = bars[index]
        wanted = intents_at(
            session, deployed, portfolio_ref=portfolio_ref, bars=list(bars), index=index
        )
        if not wanted:
            continue
        broker = PaperBroker(marks={snapshot.symbol: Decimal(str(bar.close))})
        outcome = runtime.cycle.run(  # type: ignore[attr-defined]
            session,
            portfolio_ref=portfolio_ref,
            broker=broker,
            intents=tuple(intent.as_tuple() for intent in wanted),
            proposer=actors["proposer"],
            assessor=actors["assessor"],
            approver=actors["approver"],
            executor=actors["executor"],
            analyst=actors["analyst"],
            at=bar.timestamp,
        )
        turns += 1
        orders.extend(outcome.orders)
        refused.extend(outcome.refused)
        notes.extend(outcome.notes[:1])

    return PaperWalk(
        portfolio_ref=portfolio_ref,
        snapshot_ref=snapshot.ref,
        first_bar=start,
        bars=end - start,
        turns=turns,
        orders=tuple(orders),
        refused=tuple(refused),
        notes=notes[:12],
    )


# ------------------------------------------------- what the book actually did


def sleeve_curve(
    session: Session,
    *,
    portfolio_ref: str,
    version_ref: str,
    bars: list[object],
    first_bar: int,
    sleeve: Decimal,
) -> list[Decimal]:
    """Mark-to-market equity per bar, derived from the fills.

    Rebuilt from the record rather than accumulated during the walk, so the
    curve the gap is measured on is a consequence of what the database says
    happened. Cash starts at the sleeve; every fill moves cash by its signed
    notional plus its fee; the holding is marked at each bar's close.
    """
    rows = list(
        session.execute(
            sa.select(Order.side, Fill.quantity, Fill.price, Fill.fee, Fill.filled_at)
            .join(Fill, Fill.order_ref == Order.ref)
            .where(Order.portfolio_ref == portfolio_ref, Order.version_ref == version_ref)
            .order_by(Fill.filled_at)
        ).all()
    )
    cash = sleeve
    holding = Decimal(0)
    cursor = 0
    curve: list[Decimal] = []
    for bar in bars[first_bar:]:
        stamp = bar.timestamp  # type: ignore[attr-defined]
        while cursor < len(rows) and rows[cursor][4] <= stamp:
            side, quantity, price, fee, _ = rows[cursor]
            signed = quantity if side == OrderSide.BUY.value else -quantity
            cash -= signed * price
            cash -= fee
            holding += signed
            cursor += 1
        curve.append(cash + holding * Decimal(str(bar.close)))  # type: ignore[attr-defined]
    return curve


def realised(
    curve: list[Decimal], *, trades: int, costs: Decimal
) -> dict[str, Decimal]:
    """The paper period's metrics, through the engine's own measurements.

    Deliberately the same functions the backtest used. Two implementations of
    "Sharpe" would put a difference between them into every gap and label it a
    finding about the market.
    """
    if len(curve) < 2:
        raise IntegrityViolation(
            "a curve of fewer than two marks has no return to measure"
        )
    start, end = curve[0], curve[-1]
    returns = [
        curve[i] / curve[i - 1] - Decimal(1)
        for i in range(1, len(curve))
        if curve[i - 1]
    ]
    sharpe, _low, _high = LocalEngine.sharpe_with_interval(returns)
    return {
        "total_return": ((end / start - Decimal(1)) if start else Decimal(0)).quantize(
            _QUANTUM
        ),
        "sharpe": sharpe,
        "max_drawdown": LocalEngine.max_drawdown(curve),
        "n_trades": Decimal(trades),
        "turnover": (Decimal(trades) / Decimal(len(curve))).quantize(_QUANTUM),
        "cost_drag": ((costs / start) if start else Decimal(0)).quantize(_QUANTUM),
    }


def _fills_of(
    session: Session, *, portfolio_ref: str, version_ref: str
) -> tuple[int, Decimal]:
    """How many fills, and what they cost in total.

    Cost is the fee **plus the slippage**, because the engine's ``cost_drag``
    charges the whole declared cost model — fees, spread and slippage — and a
    paper figure counting only the explicit fee would compare two different
    quantities under one name. The spread here is not modelled: it is the
    difference between the price the strategy expected and the price the broker
    actually returned, signed so that a worse fill costs more.
    """
    rows = list(
        session.execute(
            sa.select(
                Order.side, Order.expected_price, Fill.quantity, Fill.price, Fill.fee
            )
            .join(Fill, Fill.order_ref == Order.ref)
            .where(Order.portfolio_ref == portfolio_ref, Order.version_ref == version_ref)
        ).all()
    )
    total = Decimal(0)
    for side, expected, quantity, price, fee in rows:
        signed = Decimal(1) if side == OrderSide.BUY.value else Decimal(-1)
        total += fee + (price - expected) * signed * quantity
    return len(rows), total


def measure(
    runtime: object,
    session: Session,
    *,
    portfolio_ref: str,
    snapshot: MarketSnapshot,
    walked: PaperWalk,
    at: dt.datetime | None = None,
) -> tuple[Gap, ...]:
    """Compare each deployment's paper period against what its backtest claimed.

    Only metrics the supporting run actually measured are compared, and the
    expectation is read from that run's own result rows with the artifact
    digest attached. A metric the backtest never produced is skipped rather
    than defaulted: a gap against an expectation nobody stated is a comparison
    with nothing.
    """
    deployed = deployments(session, portfolio_ref=portfolio_ref, snapshot=snapshot)
    source = SnapshotSource(session, snapshot)
    bars = source.bars(snapshot.symbol, limit=0)
    gaps: list[Gap] = []

    for item in deployed:
        curve = sleeve_curve(
            session,
            portfolio_ref=portfolio_ref,
            version_ref=item.version_ref,
            bars=list(bars),
            first_bar=walked.first_bar,
            sleeve=item.sleeve,
        )
        trades, costs = _fills_of(
            session, portfolio_ref=portfolio_ref, version_ref=item.version_ref
        )
        produced = realised(curve, trades=trades, costs=costs)
        measured = {
            metric
            for metric in session.execute(
                sa.select(Result.metric).where(Result.run_ref == item.run_ref)
            ).scalars()
        }
        for metric, value in produced.items():
            if metric not in measured:
                continue
            gaps.append(
                runtime.posttrade.measure_gap(  # type: ignore[attr-defined]
                    session,
                    version_ref=item.version_ref,
                    portfolio_ref=portfolio_ref,
                    desk=item.desk,
                    metric=metric,
                    run_ref=item.run_ref,
                    realised=value,
                    period_start=bars[walked.first_bar].timestamp,
                    period_end=bars[-1].timestamp,
                    observations=len(curve),
                    realised_source=(
                        f"paper walk on {snapshot.ref} bars "
                        f"{walked.first_bar}-{len(bars) - 1}, "
                        f"{trades} fill(s) through the paper broker"
                    ),
                    at=at,
                )
            )
    return tuple(gaps)
