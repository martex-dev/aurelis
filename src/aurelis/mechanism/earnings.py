"""Whether a scheme's paper trading made money after costs (M55).

A candidate scheme is chosen on calibration: its sealed predictions beat the
instrument's own drift (ADR-0040). That says the direction calls are better
than chance. It does not say they pay: a scheme can be right more often than
the drift and still lose, when the moves it is right about are smaller than
its fees and the slippage of an order placed an hour after the trigger. Until
now the paper book's P&L was reported and never read.

This module reads it, the same way the calibration is read:

* **Round trips closed at their horizon, after fees.** A position held past
  its horizon by an outage is the outage's result and is left out (M45).
* **By independent episode.** Trades are grouped by the episodes of the
  predictions they were opened on, so thirty positions opened in one hour
  across correlated instruments are one outcome, not thirty.
* **By a sign test on episodes.** An episode that made money is a head. A
  scheme is **earning after costs** when it made money in total and its
  winning episodes beat a coin at a bar divided by the number of schemes
  with enough episodes: calling the best of several paper books "earning" is
  a search. It is **losing after costs** when it lost in total and its losing
  episodes beat a coin at 0.05, not divided: a stop protects the book, and a
  stop that waited for the family bar would let a losing scheme run for
  months.

A scheme losing after costs opens no new positions. Its open ones close at
their horizon, its predictions keep being sealed and scored, and the
suspension is on the record with the numbers.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.enums import EventKind
from aurelis.core.stats import sign_test
from aurelis.judgement.tables import Thesis
from aurelis.mechanism.library import MIN_EPISODES, episodes_of
from aurelis.mechanism.paper import is_late
from aurelis.mechanism.tables import Mechanism, MechanismTrade

__all__ = [
    "ALPHA",
    "STOP_ALPHA",
    "Earnings",
    "earnings_board",
    "earnings_of",
    "family_bar",
    "judge",
    "suspend_if_losing",
    "suspended",
]

ALPHA = Decimal("0.05")
"""The family-wise rate for calling a scheme earning, before it is divided."""

STOP_ALPHA = Decimal("0.05")
"""The rate for stopping a losing scheme. Not divided: see the module."""

_CENT = Decimal("0.01")
_P = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class Earnings:
    """One scheme's paper record after costs, read by episode."""

    mechanism_ref: str
    round_trips: int
    episodes: int
    won: int
    lost: int
    pnl: Decimal
    worst_episode: Decimal | None
    drawdown: Decimal
    """The deepest fall of the running P&L below its own high, round trip by
    round trip in the order they closed."""

    p_earn: Decimal | None
    p_lose: Decimal | None
    bar: Decimal
    verdict: str

    @property
    def enough(self) -> bool:
        return self.episodes >= MIN_EPISODES

    @property
    def earning(self) -> bool:
        return self.verdict == "earning after costs"

    @property
    def losing(self) -> bool:
        return self.verdict == "losing after costs"

    def describe(self) -> str:
        if not self.round_trips:
            return f"{self.mechanism_ref}: no round trip closed at its horizon yet"
        return (
            f"{self.mechanism_ref}: {self.round_trips} round trip(s) over {self.episodes} "
            f"episode(s), P&L {self.pnl} after fees; {self.won} episode(s) made money, "
            f"{self.lost} lost; worst episode {self.worst_episode}, drawdown {self.drawdown}"
            f" -- {self.verdict}"
        )


def _closed_on_time(session: Session, mechanism: Mechanism) -> list[tuple[Thesis, MechanismTrade]]:
    rows = session.execute(
        sa.select(Thesis, MechanismTrade)
        .join(MechanismTrade, MechanismTrade.thesis_ref == Thesis.ref)
        .where(
            MechanismTrade.mechanism_ref == mechanism.ref,
            MechanismTrade.close_order_ref.is_not(None),
            MechanismTrade.pnl.is_not(None),
        )
    ).all()
    return [
        (thesis, trade)
        for thesis, trade in rows
        if not is_late(trade, thesis.resolves_at, thesis.horizon_hours)
    ]


def _utc(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def _tally(session: Session, mechanism: Mechanism) -> tuple[list[Decimal], list[Decimal]]:
    """Each episode's P&L, and each round trip's in the order they closed."""
    trades = _closed_on_time(session, mechanism)
    pnl_of = {thesis.ref: Decimal(str(trade.pnl)) for thesis, trade in trades}
    episodes = episodes_of([thesis for thesis, _ in trades], mechanism.horizon_hours)
    by_episode = [sum((pnl_of[t.ref] for t in episode), Decimal(0)) for episode in episodes]
    in_order = [
        Decimal(str(trade.pnl))
        for _, trade in sorted(trades, key=lambda r: _utc(r[1].closed_at or r[1].opened_at))
    ]
    return by_episode, in_order


def family_bar(measured: int) -> Decimal:
    """The bar a scheme's winning episodes must clear to call it earning."""
    return (ALPHA / max(measured, 1)).quantize(_P)


def judge(
    mechanism_ref: str,
    by_episode: list[Decimal],
    round_trips: list[Decimal],
    *,
    bar: Decimal,
) -> Earnings:
    """Read one scheme's paper record. Pure: the rules, and nothing else.

    ``by_episode`` is each episode's P&L after fees; ``round_trips`` is each
    round trip's, in the order they closed, for the drawdown.
    """
    won = sum(1 for p in by_episode if p > 0)
    lost = sum(1 for p in by_episode if p < 0)
    decided = won + lost
    total = sum(by_episode, Decimal(0))
    running = peak = drawdown = Decimal(0)
    for pnl in round_trips:
        running += pnl
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
    p_earn = sign_test(won, decided) if decided else None
    p_lose = sign_test(lost, decided) if decided else None
    if len(by_episode) < MIN_EPISODES:
        verdict = f"gathering ({len(by_episode)}/{MIN_EPISODES} paper episodes)"
    elif total > 0 and p_earn is not None and p_earn < bar:
        verdict = "earning after costs"
    elif total < 0 and p_lose is not None and p_lose < STOP_ALPHA:
        verdict = "losing after costs"
    else:
        verdict = "not distinguishable from luck"
    return Earnings(
        mechanism_ref=mechanism_ref,
        round_trips=len(round_trips),
        episodes=len(by_episode),
        won=won,
        lost=lost,
        pnl=total.quantize(_CENT),
        worst_episode=min(by_episode).quantize(_CENT) if by_episode else None,
        drawdown=drawdown.quantize(_CENT),
        p_earn=p_earn,
        p_lose=p_lose,
        bar=bar,
        verdict=verdict,
    )


def earnings_board(session: Session) -> dict[str, Earnings]:
    """Every mechanism that has traded, judged at the bar for the family."""
    traded = set(session.execute(sa.select(MechanismTrade.mechanism_ref).distinct()).scalars())
    tallies = {
        m.ref: _tally(session, m)
        for m in session.execute(
            sa.select(Mechanism).where(Mechanism.ref.in_(traded)).order_by(Mechanism.ref)
        ).scalars()
    }
    bar = family_bar(sum(1 for e, _ in tallies.values() if len(e) >= MIN_EPISODES))
    return {ref: judge(ref, e, r, bar=bar) for ref, (e, r) in tallies.items()}


def earnings_of(session: Session, mechanism_ref: str) -> Earnings:
    board = earnings_board(session)
    if mechanism_ref in board:
        return board[mechanism_ref]
    return Earnings(
        mechanism_ref,
        0,
        0,
        0,
        0,
        Decimal("0.00"),
        None,
        Decimal("0.00"),
        None,
        None,
        ALPHA,
        f"gathering (0/{MIN_EPISODES} paper episodes)",
    )


def suspended(session: Session, mechanism_ref: str) -> bool:
    """Whether the mechanism was suspended from paper trading for losing."""
    from aurelis.platform.db.tables import Event

    return (
        session.execute(
            sa.select(sa.func.count()).where(
                Event.kind == EventKind.MECHANISM_SUSPENDED.value,
                Event.subject == mechanism_ref,
            )
        ).scalar_one()
        > 0
    )


def suspend_if_losing(
    session: Session, earnings: Earnings, *, ledger: Any, actor: str, at: dt.datetime
) -> bool:
    """Record the suspension once, when the record first says it is losing.

    Returns whether the mechanism is suspended now. Once suspended it stays
    so: its record stops growing when it stops trading, and a scheme that
    lost after costs does not get to trade its way back on paper luck.
    """
    if suspended(session, earnings.mechanism_ref):
        return True
    if not earnings.losing:
        return False
    ledger.append(
        session,
        kind=EventKind.MECHANISM_SUSPENDED,
        actor=actor,
        subject=earnings.mechanism_ref,
        payload={
            "because": "losing after costs",
            "round_trips": earnings.round_trips,
            "episodes": earnings.episodes,
            "won": earnings.won,
            "lost": earnings.lost,
            "pnl": str(earnings.pnl),
            "p_lose": str(earnings.p_lose),
            "drawdown": str(earnings.drawdown),
        },
        at=at,
    )
    return True
