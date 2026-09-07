"""M12 — multi-desk expansion.

Named after the acceptance criterion in ``docs/07-roadmap.md``:

* each desk runs a complete mission end to end,
* and its research is comparable across desks in the ledger.

Plus the properties that make the second one true: that a metric is converted
through its own desk's calendar, that a comparison which cannot be made is
refused rather than fudged, and that a desk whose data cannot move is refused
outright.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from aurelis.desks.calendars import CALENDARS, calendar_for
from aurelis.desks.comparability import (
    METRIC_SCALING,
    Incomparable,
    Scaling,
    annualise,
    compare,
)
from aurelis.desks.costs import DESK_COSTS, costs_for
from aurelis.desks.demonstration import run_multi_desk
from aurelis.desks.limits import limits_for
from aurelis.desks.power import bars_for_span, required_observations
from aurelis.desks.readiness import Readiness, assess
from aurelis.desks.sources import DESK_FIXTURES, fixture_for, live_feed_status
from aurelis.desks.tables import DeskOpening
from aurelis.engines.local import LocalEngine
from aurelis.org.desks import DESKS, Desk
from aurelis.research.states import Verdict
from aurelis.runtime import Runtime

SPAN = Decimal("0.05")
"""A short budget for the tests. The finding is about how the seven desks
relate to each other, which does not depend on the size of the budget."""


@pytest.fixture
def staffed(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


@pytest.fixture(scope="module")
def multi_desk() -> object:
    """The demonstration, run once for the whole module."""
    import datetime as dt
    import shutil
    import tempfile
    from pathlib import Path

    from aurelis.core.clock import FrozenClock
    from aurelis.core.config import Settings
    from aurelis.platform.llm.providers import MockProvider

    home = Path(tempfile.mkdtemp(prefix="aurelis-m12-"))
    settings = Settings(
        home=home,
        provider="mock",
        cache_models=True,
        strict_integrity=True,
        company_budget_usd="10",
        company_budget_tokens=1_000_000,
    )
    built = Runtime.build(
        settings,
        clock=FrozenClock(dt.datetime(2026, 9, 7, 9, 0, tzinfo=dt.UTC)),
        provider=MockProvider(),
    )
    built.initialise()
    built.staff()
    try:
        yield run_multi_desk(built, span=SPAN)
    finally:
        built.close()
        shutil.rmtree(home, ignore_errors=True)


# ---------------------------------------------------------------- calendars


def test_every_desk_runs_on_a_declared_calendar() -> None:
    """A desk whose clock is unknown cannot have its research annualised."""
    for desk, spec in DESKS.items():
        assert spec.calendar in CALENDARS, desk
        assert calendar_for(desk.value).periods_per_year("1h") > 0


def test_a_calendar_refuses_an_interval_it_has_not_declared() -> None:
    """A guessed conversion factor silently rescales every Sharpe on the desk."""
    nyse = CALENDARS["XNYS"]
    assert nyse.periods_per_year("1d") == 252
    with pytest.raises(KeyError, match="has not declared"):
        nyse.periods_per_year("15m")


def test_the_nyse_hour_count_is_not_the_naive_one() -> None:
    """252 sessions of 6.5 hours is 1638, not 8760 and not 6132.

    Getting this wrong rescales every annualised figure on the desk by a
    factor of 2.3, in a direction that flatters it.
    """
    assert CALENDARS["XNYS"].periods_per_year("1h") == 1638
    assert CALENDARS["24/7"].periods_per_year("1h") == 8760


def test_an_equities_fixture_produces_no_weekend_bars() -> None:
    """A backtest that traded an S&P name on a Sunday is obviously wrong on a
    real feed and silently fine on a naive fixture."""
    bars = fixture_for(Desk.EQUITIES).bars("ACME", limit=200)
    assert bars
    assert all(bar.timestamp.weekday() < 5 for bar in bars)
    assert all(14 <= bar.timestamp.hour < 21 for bar in bars)

    crypto = fixture_for(Desk.MEMECOIN).bars("PEPO", limit=200)
    assert any(bar.timestamp.weekday() >= 5 for bar in crypto)


# ------------------------------------------------------------ comparability


def test_a_per_bar_sharpe_is_converted_through_its_own_desks_calendar() -> None:
    """The same raw number means different things on different desks."""
    raw = Decimal("0.05")
    crypto = annualise("sharpe", raw, desk="crypto", interval="1h")
    equities = annualise("sharpe", raw, desk="equities", interval="1h")

    assert crypto.raw == equities.raw == raw
    assert crypto.value > equities.value
    ratio = crypto.value / equities.value
    assert Decimal("2.3") < ratio < Decimal("2.4")
    assert crypto.converted and crypto.factor > 1
    assert "8760" in crypto.describe() or crypto.periods_per_year == 8760


def test_a_level_metric_is_not_rescaled() -> None:
    """Total return over a window does not care how finely it was sampled."""
    total = annualise("total_return", Decimal("0.2"), desk="crypto", interval="1h")
    assert total.scaling is Scaling.LEVEL
    assert total.factor == Decimal(1)
    assert total.value == Decimal("0.2")
    assert not total.converted


def test_a_metric_with_no_declared_scaling_is_refused() -> None:
    """Passing an unknown metric through is how an unconverted rate hides."""
    assert "sharpe" in METRIC_SCALING
    with pytest.raises(Incomparable, match="no declared scaling"):
        annualise("mystery_ratio", Decimal("1"), desk="crypto")


def test_a_count_is_not_turned_into_a_rate() -> None:
    """A trade count on an hourly desk and one on a daily desk are different
    questions, not the same question at two scales."""
    with pytest.raises(Incomparable, match="is a count"):
        annualise("n_trades", Decimal("40"), desk="crypto", interval="1h")


def test_two_measurements_over_different_windows_are_refused() -> None:
    """Annualisation fixes the frequency. It does nothing about the window, and
    a converted comparison of a quarter against a decade looks rigorous."""
    left = annualise("sharpe", Decimal("0.05"), desk="crypto", interval="1h")
    right = annualise("sharpe", Decimal("0.04"), desk="equities", interval="1h")
    assert "crypto" in compare(left, right, bars=(1000, 1200))
    with pytest.raises(Incomparable, match="does nothing about the windows"):
        compare(left, right, bars=(1000, 10000))


# ------------------------------------------------------------------- power


def test_the_same_claim_needs_the_same_years_on_every_desk() -> None:
    """And a completely different number of bars.

    A high-frequency desk chases a smaller per-bar effect and needs more bars;
    the two cancel exactly, and the span is what is really being asked for.
    """
    spans = set()
    bars = {}
    for desk in DESKS:
        need = required_observations(
            desk.value, annualised_claim=Decimal("1.0"), interval="1h"
        )
        spans.add(need.years_required)
        bars[desk.value] = need.bars_required

    assert len(spans) == 1, spans
    assert bars["crypto"] > bars["equities"] * 5


def test_a_budget_in_bars_is_not_a_budget() -> None:
    """The same bar count is a different amount of time on every desk."""
    quarter = {
        desk.value: bars_for_span(desk.value, years=Decimal("0.25"))
        for desk in DESKS
    }
    assert quarter["crypto"] == 2190
    assert quarter["equities"] == 410
    assert quarter["crypto"] > quarter["equities"] * 5


# --------------------------------------------------------- costs and limits


def test_every_desk_charges_something() -> None:
    """A backtest without costs is not evidence."""
    for desk in DESKS:
        model = costs_for(desk)
        assert model.round_trip_bps > 0, desk
        assert model.basis.strip(), desk


def test_the_desks_do_not_share_a_cost_model() -> None:
    """The whole point of a desk is that trading it is not like trading another."""
    round_trips = {d.value: costs_for(d).round_trip_bps for d in DESKS}
    assert len(set(round_trips.values())) >= 5
    assert round_trips["memecoin"] > round_trips["fx"] * 100
    assert round_trips["options"] > round_trips["equities"] * 5


def test_carry_is_charged_on_time_held_not_on_turnover() -> None:
    """A slow strategy does not escape funding, and a fast one barely pays it.

    Folding carry into the spread would flatter every low-turnover strategy on
    a carry desk.
    """
    crypto = costs_for(Desk.CRYPTO)
    periods = calendar_for("crypto").periods_per_year("1h")
    brief = crypto.carry_for(24, periods)
    long_held = crypto.carry_for(periods, periods)
    assert long_held > brief * 100
    assert crypto.engine_costs().round_trip_bps == crypto.round_trip_bps

    equities = costs_for(Desk.EQUITIES)
    assert equities.carry_for(100, periods) >= 0


def test_a_desks_position_ceiling_is_its_own_liquidity() -> None:
    """Not a policy number. A strategy that needs more than the market bears
    has found a number rather than an edge."""
    for desk in DESKS:
        assert limits_for(desk).max_position_usd == costs_for(desk).liquidity.material_size_usd
    assert not limits_for(Desk.MEMECOIN).shortable


# --------------------------------------------------------------- readiness


def test_every_desk_passes_its_readiness_checklist() -> None:
    for desk in DESKS:
        assessment = assess(desk)
        assert assessment.may_open, assessment.describe()


def test_no_desk_reads_as_having_live_data() -> None:
    """Fixtures are provisional, never a pass. A desk cannot quietly graduate
    from 'open on fixtures' to 'open'."""
    for desk in DESKS:
        data = next(i for i in assess(desk).items if i.name == "data")
        assert data.state is Readiness.PROVISIONAL, desk
        assert "not a market" in data.detail or "No live" in data.detail
    assert len(live_feed_status()) == len(DESKS)


def test_a_desk_whose_prices_cannot_move_is_refused() -> None:
    """Two desks shipped completely flat and nothing caught it: the engine ran,
    the metrics computed, and the verdict rule said UNDERPOWERED without
    anything reporting that the input had been a constant."""
    from aurelis.desks.readiness import _prices_move
    from aurelis.desks.sources import DESK_FIXTURES as LIVE
    from aurelis.desks.sources import DeskFixture, DeskUniverse

    for desk, fixture in LIVE.items():
        assert fixture.moves(), desk

    flat = DeskFixture(
        desk=Desk.FX,
        universe=DeskUniverse(
            survivors=("EURUSD",),
            casualties={},
            base={"EURUSD": Decimal(1)},
            volatility=Decimal("0.006"),
            # A cent tick on a price of 1.00: every move rounds away.
            tick=Decimal("0.01"),
        ),
        calendar=calendar_for("fx"),
    )
    assert not flat.moves()

    original = LIVE[Desk.FX]
    LIVE[Desk.FX] = flat
    try:
        item = _prices_move(Desk.FX)
        assert item.state is Readiness.FAIL
        assert "constant series" in item.detail
        assert not assess(Desk.FX).may_open
    finally:
        LIVE[Desk.FX] = original


def test_the_engine_covers_every_desk_that_has_a_universe() -> None:
    covered = LocalEngine().capabilities().desks
    assert covered == {"crypto", *(d.value for d in DESK_FIXTURES)}
    assert covered == {d.value for d in DESKS}


# -------------------------------------------- acceptance: a mission per desk


def test_each_desk_runs_a_complete_mission_end_to_end(multi_desk) -> None:  # type: ignore[no-untyped-def]
    """The first acceptance criterion.

    Propose, screen, preregister, design, run, conclude — on all seven, each
    with its own calendar, cost model, universe and casualties.
    """
    outcome = multi_desk
    assert outcome.desks == len(DESKS)
    seen = {r.desk for r in outcome.results}
    assert seen == set(DESKS)

    for result in outcome.results:
        assert result.hypothesis_ref.startswith("HYP-")
        assert result.registration_ref.startswith("REG-")
        assert result.run_ref.startswith("RUN-")
        assert isinstance(result.verdict, Verdict)
        assert result.universe, result.desk
        assert result.caveats, "a desk opened on fixtures carries its caveats"


def test_each_desk_charged_its_own_costs(multi_desk) -> None:  # type: ignore[no-untyped-def]
    """The same rule, seven different cost models. This is what a desk is."""
    charged = {r.desk.value: Decimal(r.round_trip_bps) for r in multi_desk.results}
    for desk in DESKS:
        assert charged[desk.value] == DESK_COSTS[desk].round_trip_bps
    assert len(set(charged.values())) >= 5


def test_research_is_comparable_across_desks(multi_desk) -> None:
    """The second acceptance criterion.

    Every figure converted through its own desk's calendar, with the factor
    recorded so a reader can undo it.
    """
    outcome = multi_desk
    for result in outcome.results:
        assert result.annualised is not None, result.desk
        assert result.annualised.factor == calendar_for(
            result.desk.value
        ).annualisation("1h")
        assert result.annualised.calendar == result.calendar

    factors = {r.annualised.factor for r in outcome.results if r.annualised}
    assert len(factors) > 1, "the desks do not all share one clock"
    assert "2.31" in outcome.distortion or "x more on" in outcome.distortion


def test_the_comparison_refuses_what_it_cannot_join(multi_desk) -> None:
    """Exercised, not described. Both refusals a looser system would make
    silently."""
    refusals = multi_desk.refusals
    assert any("count" in r for r in refusals)
    assert any("windows" in r for r in refusals)


def test_a_research_budget_in_bars_is_reported_as_not_a_budget(
    multi_desk,
) -> None:
    """The cross-desk finding: the same years, a factor of five in bars."""
    finding = multi_desk.budget_finding
    assert "years on every desk" in finding
    assert "not a budget" in finding
    spans = {r.power.years_required for r in multi_desk.results}
    assert len(spans) == 1


def test_the_verdicts_are_honest_about_power(multi_desk) -> None:
    """A quarter of data against a claim needing years is underpowered, and the
    rule says so rather than reading the point estimate."""
    for result in multi_desk.results:
        assert not result.power.powered
        assert result.verdict is Verdict.UNDERPOWERED


# ------------------------------------------------------------- the record


def test_opening_a_desk_records_its_checklist_and_caveats(
    staffed: Runtime,
) -> None:
    with staffed.database.session() as session:
        opened = staffed.desks.open_all(session)
        rows = {row.desk: row for row in staffed.desks.opened(session)}

    assert len(opened) == len(DESKS)
    for desk in DESKS:
        row = rows[desk.value]
        assert row.checklist, desk
        assert row.caveats, "every desk opened at M12 runs on fixtures"
        assert row.data_is_live is False
        assert row.periods_per_year > 0
        assert Decimal(row.round_trip_cost_bps) > 0


def test_the_database_refuses_a_desk_that_charges_nothing(
    staffed: Runtime,
) -> None:
    """Stored as text for exactness, and carrying the same trap as money — so
    the CHECK casts before it compares."""
    with (
        pytest.raises(Exception, match="charges_something"),
        staffed.database.engine.begin() as conn,
    ):
        conn.execute(
            sa.text(
                "INSERT INTO desk_openings (opening_id, desk, status, calendar, "
                "periods_per_year, round_trip_cost_bps, material_size_usd, "
                "max_gross_leverage, shortable, checklist, caveats, "
                "data_is_live, opened_by, opened_at, closed_reason) VALUES "
                "(:i, 'freebie', 'active', '24/7', 8760, '0', '1000', '1', 1, "
                "'[]', '[]', 0, 'operator', :t, '')"
            ),
            {"i": b"\x00" * 16, "t": "2026-09-07 00:00:00"},
        )


def test_a_desk_cannot_be_closed_without_a_reason(staffed: Runtime) -> None:
    """A desk that went quiet and one that was shut deliberately are different
    facts."""
    with staffed.database.session() as session:
        staffed.desks.open(session, Desk.FX)
        with pytest.raises(Exception, match="without a recorded reason"):
            staffed.desks.close(session, Desk.FX, reason="  ")
        staffed.desks.close(session, Desk.FX, reason="no researcher covers it")
        row = session.execute(
            sa.select(DeskOpening).where(DeskOpening.desk == "fx")
        ).scalar_one()
    assert row.status == "closed"
    assert row.closed_reason
