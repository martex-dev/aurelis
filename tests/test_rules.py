"""M26 — a strategy is a rule the agent wrote, and the engine runs it.

The rule language replaces the 72-point menu. What these tests hold it to:

* a rule parses to a canonical form that hashes the same however it was typed,
* the features are what the reference says they are,
* nothing in a rule can see the future,
* the bounds bind, and the parser refuses rather than guesses,
* the engine runs a rule through the same latency, costs and measurement as
  every registered signal.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aurelis.engines.local import SIGNALS, LocalEngine
from aurelis.engines.spec import BacktestSpec, DataSpec, ExperimentSpec, SignalSpec, UniverseSpec
from aurelis.rules import (
    MAX_CLAUSES,
    MAX_WINDOW,
    Program,
    RuleSyntaxError,
    evaluate,
    parse,
)
from aurelis.rules.language import render

_CLOSES = [Decimal(100 + (i * 7) % 13 - 6) for i in range(200)]


# ------------------------------------------------------------ canonical form


def test_a_rule_hashes_the_same_however_it_was_typed() -> None:
    one = parse("ret(24) > 0.02 -> long\nret(24) < -0.02 -> short")
    two = parse("  RET( 24 )>0.020 ->  LONG \n\n ret(24)  <  -0.02 -> short  # comment\n")
    assert one.digest == two.digest
    assert one.payload == two.payload
    assert one.source != two.source, "what was typed is kept beside the canonical form"


def test_the_canonical_text_round_trips() -> None:
    program = parse("(ret(6) > 0 and not (vol(24) > 0.05)) or rsi(14) < 30 -> long\nelse -> short")
    again = parse(render(program))
    assert again.digest == program.digest
    assert Program.from_payload(program.payload).digest == program.digest


def test_a_program_knows_its_windows_warmup_and_side() -> None:
    program = parse("sma(24) > sma(168) -> long\nclose < low(72) -> short")
    assert program.windows == (24, 72, 168)
    assert program.warmup == 168
    assert program.uses_short
    assert not parse("ret(6) > 0 -> long").uses_short


# ------------------------------------------------------------ the features


def _feature(text: str, closes: list[Decimal]) -> list[Decimal]:
    """Evaluate a rule of the form ``<feature> > <constant>`` bar by bar and
    read the feature back through comparisons -- crude, so a direct check."""
    return evaluate(parse(text), closes)


def test_ret_is_the_change_over_n_bars() -> None:
    closes = [Decimal(100), Decimal(110), Decimal(121), Decimal(133)]
    up = _feature("ret(1) > 0.09 -> long", closes)
    assert up == [Decimal(0), Decimal(1), Decimal(1), Decimal(1)]
    exact = _feature("ret(2) >= 0.21 -> long", closes)
    assert exact == [Decimal(0), Decimal(0), Decimal(1), Decimal(0)]


def test_sma_high_low_and_rsi_match_a_naive_computation() -> None:
    from aurelis.rules.language import _extreme, _rsi, _sma

    closes = _CLOSES
    n = 5
    sma = _sma(closes, n)
    high = _extreme(closes, n, highest=True)
    low = _extreme(closes, n, highest=False)
    for t in range(len(closes)):
        if t < n - 1:
            assert sma[t] is None and high[t] is None and low[t] is None
            continue
        window = closes[t - n + 1 : t + 1]
        assert sma[t] == sum(window) / n
        assert high[t] == max(window)
        assert low[t] == min(window)

    rsi = _rsi(closes, 14)
    assert rsi[13] is None and rsi[14] is not None
    assert all(Decimal(0) <= value <= Decimal(100) for value in rsi if value is not None)


def test_ema_and_vol_have_the_documented_warmup() -> None:
    from aurelis.rules.language import _ema, _vol

    ema = _ema(_CLOSES, 10)
    assert ema[8] is None and ema[9] is not None
    vol = _vol(_CLOSES, 10)
    assert vol[9] is None and vol[10] is not None
    assert all(value >= 0 for value in vol if value is not None)


# ------------------------------------------------------------ no look-ahead


def test_nothing_in_a_rule_can_see_the_future() -> None:
    program = parse(
        "ret(6) > 0.01 and ema(12) > sma(24) -> long\n"
        "rsi(14) > 70 or close > high(48) -> short\n"
        "vol(24) > 0.03 -> flat\nelse -> long"
    )
    before = evaluate(program, _CLOSES)
    altered = list(_CLOSES)
    for i in range(150, 200):
        altered[i] = Decimal(9999)
    after = evaluate(program, altered)
    assert before[:150] == after[:150], "changing the future moved the past"
    assert before[150:] != after[150:], "and the future did change"


def test_bars_inside_the_warmup_are_flat_whatever_the_clauses_say() -> None:
    program = parse("close > 0 -> long\nelse -> long")
    assert program.warmup == 0
    assert all(w == 1 for w in evaluate(program, _CLOSES))
    windowed = parse("sma(50) > 0 -> long\nelse -> long")
    weights = evaluate(windowed, _CLOSES)
    assert all(w == 0 for w in weights[:50]) and all(w == 1 for w in weights[50:])


def test_a_comparison_with_no_value_is_false_and_falls_through() -> None:
    program = parse("ret(100) > -1 -> short\nret(5) > -1 -> long")
    weights = evaluate(program, _CLOSES)
    # Warm-up is 100 (the longest window), so nothing before it trades; after
    # it, the first clause holds everywhere.
    assert all(w == 0 for w in weights[:100])
    assert all(w == -1 for w in weights[100:])


def test_division_by_zero_is_not_a_crash_and_not_a_trade() -> None:
    program = parse("close / (close - close) > 1 -> long\nelse -> short")
    assert set(evaluate(program, _CLOSES[:10])) == {Decimal(-1)}


# ------------------------------------------------------------ refusals


@pytest.mark.parametrize(
    "text",
    [
        "",
        "ret(24) > 0.02",
        "ret(24) > 0.02 -> up",
        "volume(24) > 1 -> long",
        f"ret({MAX_WINDOW + 1}) > 0 -> long",
        "ret(0) > 0 -> long",
        "ret(2.5) > 0 -> long",
        "ret(24) -> long",
        "ret(24) > 0.02 -> long\nelse -> flat\nret(6) > 0 -> short",
        "close > 0 -> flat",
        "\n".join("ret(6) > 0 -> long" for _ in range(MAX_CLAUSES + 1)),
        "ret(24) > 0.02 -> long extra",
        "import os -> long",
        "ret(24) > 0.02 -> long; ret(6) < 0 -> short",
    ],
)
def test_what_is_not_a_rule_is_refused_not_guessed(text: str) -> None:
    with pytest.raises(RuleSyntaxError):
        parse(text)


def test_a_refusal_says_which_line() -> None:
    with pytest.raises(RuleSyntaxError, match="line 2"):
        parse("ret(24) > 0.02 -> long\nfoo(3) > 1 -> short")


def test_a_rule_that_never_trades_is_refused() -> None:
    with pytest.raises(RuleSyntaxError, match="never trades"):
        parse("close > 0 -> flat\nelse -> flat")


# ------------------------------------------------------------ the engine


def _spec(text: str, *, allow_short: bool = True) -> ExperimentSpec:
    program = parse(text)
    return ExperimentSpec(
        engine="local",
        universe=UniverseSpec(
            desk="crypto", symbols=(), point_in_time=True, selection="point_in_time"
        ),
        data=DataSpec(source="fixture:crypto", bars=300, interval="1h"),
        signal=SignalSpec(
            kind="rule",
            lookback=program.warmup,
            parameters={"program": program.payload, "text": program.text},
        ),
        backtest=BacktestSpec(allow_short=allow_short, warmup_bars=program.warmup),
        metrics=("total_return", "sharpe", "max_drawdown", "n_trades"),
    )


def test_the_engine_runs_a_rule_and_the_digest_locks_the_program() -> None:
    assert "rule" in SIGNALS
    engine = LocalEngine()
    spec = _spec("ret(24) > 0.01 -> long\nret(24) < -0.01 -> short")
    first = engine.run(spec)
    second = engine.run(spec)
    assert first.metrics.get("sharpe").value == second.metrics.get("sharpe").value
    assert first.spec_digest == spec.digest()
    other = _spec("ret(24) > 0.02 -> long\nret(24) < -0.01 -> short")
    assert other.digest() != spec.digest(), "a different threshold is a different lock"


def test_a_rule_that_is_always_long_measures_as_the_always_long_baseline() -> None:
    engine = LocalEngine()
    rule = engine.run(_spec("close > 0 -> long\nelse -> long"))
    baseline_spec = _spec("close > 0 -> long")
    baseline = ExperimentSpec(
        engine="local",
        universe=baseline_spec.universe,
        data=baseline_spec.data,
        signal=SignalSpec(kind="always_long", lookback=0),
        backtest=BacktestSpec(allow_short=False, warmup_bars=0),
        metrics=baseline_spec.metrics,
    )
    reference = engine.run(baseline)
    assert rule.metrics.get("total_return").value == reference.metrics.get("total_return").value


def test_a_rule_may_not_short_where_the_spec_forbids_it() -> None:
    engine = LocalEngine()
    allowed = engine.run(_spec("ret(6) < 0 -> short", allow_short=True))
    forbidden = engine.run(_spec("ret(6) < 0 -> short", allow_short=False))
    assert allowed.metrics.get("n_trades").value > 0
    assert forbidden.metrics.get("n_trades").value == 0


def test_the_rule_kind_needs_a_program() -> None:
    engine = LocalEngine()
    spec = _spec("ret(6) > 0 -> long")
    broken = ExperimentSpec(
        engine=spec.engine,
        universe=spec.universe,
        data=spec.data,
        signal=SignalSpec(kind="rule", lookback=6, parameters={}),
        backtest=spec.backtest,
        metrics=spec.metrics,
    )
    with pytest.raises(RuleSyntaxError):
        engine.run(broken)
