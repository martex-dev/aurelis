"""Running the strategy lab (M65).

One run fetches daily history for every market in the universe: the crypto
the company is granted, plus equities, forex, commodities and futures. It
then tests every strategy in the catalogue on every series, and records each
result. It makes no model call; it is software, which is what CLAUDE.md
asks for calculations and backtests.

It runs from ``aurelis lab run``, and from the service once a week.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.enums import EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.lab.evaluate import Result, evaluate
from aurelis.lab.history import UNIVERSE, Series, fetch
from aurelis.lab.strategies import CATALOGUE
from aurelis.lab.tables import LabResult, LabRun
from aurelis.platform.db.refs import allocate_ref

__all__ = ["EVERY", "LabSummary", "crypto_universe", "lab_due", "lab_summary", "run_lab"]

EVERY = dt.timedelta(days=7)

Fetcher = Callable[[str, str, str], Series]


def crypto_universe(session: Session) -> list[str]:
    """The Coinbase products the company is granted, deduplicated."""
    from aurelis.service.tables import DataGrant

    products: list[str] = []
    for grant in session.execute(
        sa.select(DataGrant).where(DataGrant.source == "coinbase", DataGrant.revoked_at.is_(None))
    ).scalars():
        for symbol in grant.instruments or []:
            if str(symbol) not in products:
                products.append(str(symbol))
    return products or ["BTC-USD", "ETH-USD", "SOL-USD"]


def lab_due(session: Session, at: dt.datetime) -> bool:
    last = session.execute(sa.select(sa.func.max(LabRun.ran_at))).scalar()
    if last is None:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=dt.UTC)
    return at - last >= EVERY


def run_lab(runtime: Any, *, fetcher: Fetcher | None = None, at: dt.datetime | None = None) -> str:
    """Fetch, test everything on everything, and record it. Returns the run's ref."""
    moment = at or runtime.clock.now()
    get = fetcher or (lambda desk, symbol, source: fetch(desk, symbol, source))
    with runtime.database.session() as session:
        wanted = [("crypto", s, "coinbase") for s in crypto_universe(session)]
    wanted += [(desk, s, src) for desk, rows in UNIVERSE.items() for s, src in rows]

    series: list[Series] = []
    failed: list[dict[str, str]] = []
    for desk, symbol, source in wanted:
        try:
            got = get(desk, symbol, source)
        except Exception as error:  # noqa: BLE001 - one market failing is recorded, not fatal
            failed.append({"symbol": symbol, "desk": desk, "why": str(error)[:200]})
            continue
        if got.bars:
            series.append(got)
        else:
            failed.append({"symbol": symbol, "desk": desk, "why": "no bars"})

    trials = len(CATALOGUE) * len(series)
    results: list[Result] = []
    for item in series:
        for spec in CATALOGUE:
            outcome = evaluate(spec, item, n_trials=max(trials, 2))
            if outcome is not None:
                results.append(outcome)

    with runtime.database.session() as session:
        stored = [
            {
                "symbol": s.symbol,
                "desk": s.desk,
                "source": s.source,
                "bars": len(s.bars),
                "digest": runtime.artifacts.put_json(
                    session, s.payload(), kind="lab_series", produced_by="LAB"
                ).digest,
            }
            for s in series
        ]
        ref = allocate_ref(session, RefKind.LAB_RUN)
        survivors = sum(1 for r in results if r.verdict == "survived")
        session.add(
            LabRun(
                run_id=uuid7(),
                ref=ref,
                series=stored,
                failed=failed,
                tests=len(results),
                luck_trials=trials,
                survivors=survivors,
                ran_at=moment,
            )
        )
        session.add_all(
            LabResult(
                result_id=uuid7(),
                run_ref=ref,
                strategy=r.spec.name[:96],
                family=r.spec.family,
                symbol=r.symbol,
                desk=r.desk,
                bars=r.bars,
                is_sharpe=r.in_sample.sharpe,
                is_return=r.in_sample.total,
                oos_sharpe=r.out_of_sample.sharpe,
                oos_return=r.out_of_sample.total,
                oos_hold=r.out_of_sample.hold,
                oos_drawdown=r.out_of_sample.max_drawdown,
                oos_trades=r.out_of_sample.trades,
                verdict=r.verdict,
            )
            for r in results
        )
        session.flush()
        runtime.ledger.append(
            session,
            kind=EventKind.LAB_RAN,
            actor="LAB",
            subject=ref,
            payload={
                "series": len(series),
                "failed": len(failed),
                "tests": len(results),
                "survivors": survivors,
            },
            at=moment,
        )
    return ref


@dataclass(frozen=True, slots=True)
class LabSummary:
    ref: str
    ran_at: dt.datetime
    markets: int
    tests: int
    survivors: int
    failed_fetches: int
    by_verdict: dict[str, int]
    by_desk: dict[str, tuple[int, int]]
    """desk -> (tests, survivors)"""
    by_family: dict[str, tuple[int, int]]
    family_oos: dict[str, tuple[float, float]]
    """family -> (mean out-of-sample Sharpe over every market, share that beat
    holding). Averaged over all of them, so not picked for looking good."""
    best: list[LabResult]

    def line(self) -> str:
        """One line for the shared brain every seat reads."""
        desks = ", ".join(f"{d} {s}/{t}" for d, (t, s) in sorted(self.by_desk.items()))
        top = "; ".join(
            f"{r.strategy} on {r.symbol} (out-of-sample Sharpe {r.oos_sharpe}, return "
            f"{r.oos_return} against holding {r.oos_hold})"
            for r in self.best[:3]
        )
        leaning = sorted(self.family_oos.items(), key=lambda kv: kv[1][0], reverse=True)
        families = "; ".join(
            f"{name} averaged an out-of-sample Sharpe of {sharpe} and beat holding "
            f"{share}% of the time"
            for name, (sharpe, share) in leaning[:3]
        )
        return (
            f"Strategy lab {self.ref}: {self.tests} classic strategies tested on "
            f"{self.markets} markets with years of daily data, after costs; {self.survivors} "
            f"survived (beat luck in sample, then beat holding out of sample). Survivors by "
            f"desk: {desks}."
            + (f" Best survivors: {top}." if top else " None survived.")
            + (f" Across every market (not picked), {families}." if families else "")
        )


def lab_summary(session: Session) -> LabSummary | None:
    run = session.execute(sa.select(LabRun).order_by(LabRun.ran_at.desc()).limit(1)).scalar()
    if run is None:
        return None
    rows = list(session.execute(sa.select(LabResult).where(LabResult.run_ref == run.ref)).scalars())
    verdicts = Counter(r.verdict for r in rows)
    desk: dict[str, list[int]] = {}
    family: dict[str, list[int]] = {}
    for r in rows:
        for key, table in ((r.desk, desk), (r.family, family)):
            pair = table.setdefault(key, [0, 0])
            pair[0] += 1
            pair[1] += int(r.verdict == "survived")
    oos: dict[str, list[tuple[float, bool]]] = {}
    for r in rows:
        oos.setdefault(r.family, []).append((r.oos_sharpe, r.oos_return > r.oos_hold))
    family_oos = {
        name: (
            round(sum(s for s, _ in vals) / len(vals), 3),
            round(100 * sum(1 for _, b in vals if b) / len(vals), 1),
        )
        for name, vals in oos.items()
        if vals
    }
    best = sorted(
        (r for r in rows if r.verdict == "survived"), key=lambda r: r.oos_sharpe, reverse=True
    )
    return LabSummary(
        ref=run.ref,
        ran_at=run.ran_at,
        markets=len(run.series or []),
        tests=run.tests,
        survivors=run.survivors,
        failed_fetches=len(run.failed or []),
        by_verdict=dict(verdicts),
        by_desk={k: (v[0], v[1]) for k, v in desk.items()},
        by_family={k: (v[0], v[1]) for k, v in family.items()},
        family_oos=family_oos,
        best=best[:10],
    )
