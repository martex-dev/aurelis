"""M65 — the strategy lab: every taught strategy, on every desk, tested honestly.

The acceptance criteria, each with a test named after it:

* no strategy can see the future: changing a later bar never changes an
  earlier position,
* the luck bar rises with the number of strategies tried and falls with the
  years tested,
* a planted edge survives, and noise tested many ways does not,
* costs are charged, and a strategy that churns pays for it,
* a run records what it tested on, every result and what failed to fetch,
  append-only,
* every seat reads the lab's finding, and the Office shows it,
* the service runs it once a week.
"""

from __future__ import annotations

import datetime as dt
import random
from collections import Counter
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import FeedUnavailable
from aurelis.lab.evaluate import evaluate, luck_bar
from aurelis.lab.history import Series
from aurelis.lab.run import EVERY, lab_due, lab_summary, run_lab
from aurelis.lab.strategies import CATALOGUE, Spec, positions_for
from aurelis.lab.tables import LabResult
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime

_NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.UTC)


def _series(returns: list[float], *, desk: str = "equities", symbol: str = "TEST") -> Series:
    price, bars = 100.0, []
    for i, r in enumerate(returns):
        new = price * (1 + r)
        hi, lo = max(price, new) * 1.002, min(price, new) * 0.998
        bars.append((1_600_000_000 + i * 86_400, price, hi, lo, new, 1000.0))
        price = new
    return Series(symbol=symbol, desk=desk, source="test", bars=tuple(bars))


def _walk(n: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0003, 0.01) for _ in range(n)]


def test_no_strategy_can_see_the_future() -> None:
    base = _series(_walk(600, 1)).bars
    cut = 400
    altered = list(base)
    rng = random.Random(9)
    for i in range(cut + 1, len(altered)):
        t, o, h, low, c, v = altered[i]
        k = 1 + rng.uniform(-0.2, 0.2)
        altered[i] = (t, o * k, h * k * 1.05, low * k * 0.95, c * k, v)
    for spec in CATALOGUE:
        before = positions_for(spec, base)[: cut + 1]
        after = positions_for(spec, tuple(altered))[: cut + 1]
        assert before == after, f"{spec.name} changed its past when the future changed"


def test_the_luck_bar_rises_with_tries_and_falls_with_years() -> None:
    assert luck_bar(10, 5) < luck_bar(1000, 5) < luck_bar(100_000, 5)
    assert luck_bar(1000, 20) < luck_bar(1000, 5)
    assert luck_bar(1, 5) == 0.0


def test_a_planted_edge_survives_and_noise_tried_many_ways_does_not() -> None:
    # Tomorrow strongly undoes today: what a short-period RSI reversion is for.
    rng = random.Random(3)
    planted, prev = [], 0.0
    for _ in range(1500):
        prev = -0.6 * prev + rng.gauss(0.0, 0.012)
        planted.append(prev)
    spec = Spec("rsi_reversion", (("high", 90), ("low", 10), ("period", 2)), False)
    result = evaluate(spec, _series(planted), n_trials=2)
    assert result is not None and result.verdict == "survived", result

    verdicts: Counter[str] = Counter()
    for seed in range(6):
        noise = _series(_walk(1500, 100 + seed))
        for spec in CATALOGUE:
            outcome = evaluate(spec, noise, n_trials=len(CATALOGUE) * 6)
            if outcome is not None:
                verdicts[outcome.verdict] += 1
    assert verdicts["survived"] <= 0.02 * sum(verdicts.values()), verdicts


def test_costs_are_charged_and_churning_pays_for_it() -> None:
    noise = _series(_walk(1500, 7), desk="crypto")
    churn = Spec("fvg_ict", (("hold", 3),), False)
    cheap = _series(_walk(1500, 7), desk="fx")
    on_crypto = evaluate(churn, noise, n_trials=2)
    on_fx = evaluate(churn, cheap, n_trials=2)
    assert on_crypto is not None and on_fx is not None
    assert on_crypto.out_of_sample.trades > 20
    # Same bars, same trades; crypto's round trip costs ten times FX's.
    assert on_crypto.out_of_sample.total < on_fx.out_of_sample.total


def test_too_short_a_history_is_not_judged() -> None:
    assert evaluate(CATALOGUE[0], _series(_walk(100, 1)), n_trials=2) is None


# ------------------------------------------------------------ a run


@pytest.fixture
def company(settings: Settings) -> Any:
    built = Runtime.build(
        settings, clock=FrozenClock(_NOW), provider=MockProvider(responder=standins())
    )
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _fetcher(desk: str, symbol: str, source: str) -> Series:
    if symbol == "NG=F":
        raise FeedUnavailable("yahoo could not be reached")
    seed = sum(map(ord, symbol))
    return _series(_walk(800, seed), desk=desk, symbol=symbol)


def test_a_run_records_what_it_tested_every_result_and_what_failed(company: Runtime) -> None:
    ref = run_lab(company, fetcher=_fetcher, at=_NOW)
    with company.database.session() as session:
        summary = lab_summary(session)
        rows = session.execute(sa.select(sa.func.count()).select_from(LabResult)).scalar_one()
        failed = session.execute(sa.text("SELECT failed FROM lab_runs")).scalar_one()
        events = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = 'lab.ran'")
        ).scalar_one()
    assert summary is not None and summary.ref == ref
    assert summary.markets >= 30 and rows == summary.tests == summary.markets * len(CATALOGUE)
    assert "NG=F" in str(failed)
    assert set(summary.by_desk) >= {"crypto", "equities", "fx", "commodities", "futures"}
    assert events == 1
    with company.database.session() as session, pytest.raises(sa.exc.DatabaseError):
        session.execute(sa.update(LabResult).values(verdict="survived"))
        session.flush()


def test_every_seat_reads_the_lab_and_the_office_shows_it(company: Runtime) -> None:
    from aurelis.brain.briefing import briefing
    from aurelis.station.app import station_app

    run_lab(company, fetcher=_fetcher, at=_NOW)
    with company.database.session() as session:
        text = briefing(session).text()
    assert "Lab:" in text and "classic strategies tested on" in text
    assert "Across every market (not picked)" in text
    app = station_app(company)
    room = app.handle("/office/room/quantitative_research", {}).body.decode()
    assert "data-src='/office/tab/lab'" in room
    tab = app.handle("/office/tab/lab", {}).body.decode()
    assert "by family, averaged over every market" in tab and "survived" in tab


def test_the_service_runs_the_lab_once_a_week(company: Runtime) -> None:
    with company.database.session() as session:
        assert lab_due(session, _NOW)
    run_lab(company, fetcher=_fetcher, at=_NOW)
    with company.database.session() as session:
        assert not lab_due(session, _NOW + EVERY / 2)
        assert lab_due(session, _NOW + EVERY)
