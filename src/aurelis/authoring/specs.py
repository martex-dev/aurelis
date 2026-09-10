"""Turning a rule into the experiment that measures it, and the references.

Everything the agent wrote is in ``signal``: the program, canonical and
hashed, plus its warm-up and whether it takes a short. Everything the agent may
**not** choose — the desk's costs, a point-in-time universe, the warm-up that
keeps the priming window untraded — is set here from the desk, identically for
every rule. That is the same boundary M15 drew and it is the one the company's
own critic is scored on: ``COST_UNDERSTATED``, ``SURVIVORSHIP`` and
``LOOKAHEAD`` are three of the defects it exists to catch, and an authoring
surface that let the agent set costs, universe or warm-up would let it plant
one.
"""

from __future__ import annotations

from decimal import Decimal

from aurelis.desks.costs import costs_for
from aurelis.engines.spec import (
    BacktestSpec,
    DataSpec,
    ExperimentSpec,
    SignalSpec,
    UniverseSpec,
)
from aurelis.org.desks import Desk
from aurelis.rules.language import Program

__all__ = ["BASELINES", "baseline_spec", "render_spec"]

BASELINES: tuple[str, ...] = ("always_long", "never_trade")
"""What an authored rule is measured against, and may not be.

Neither is authorable as a *reference*: an agent can of course write a rule
that is always long, and it will be measured and will tie. What it cannot do is
write the reference itself. A rule that cannot beat holding the asset has not
found anything, and one that cannot beat doing nothing has found less.
"""


def render_spec(
    program: Program,
    *,
    desk: Desk | str,
    bars: int,
    interval: str = "1h",
    seed: int = 0,
    source: str = "",
) -> ExperimentSpec:
    """The experiment that measures ``program`` on ``desk``.

    ``source`` names the data and is part of the digest that gets locked, so a
    registration cannot be honoured by a run against different bars.
    """
    the_desk = desk if isinstance(desk, Desk) else Desk(desk)
    return ExperimentSpec(
        engine="local",
        universe=UniverseSpec(
            desk=the_desk.value,
            symbols=(),
            point_in_time=True,
            selection="point_in_time",
        ),
        data=DataSpec(
            source=source or f"fixture:{the_desk.value}",
            bars=bars,
            interval=interval,
        ),
        signal=SignalSpec(
            kind="rule",
            lookback=program.warmup,
            threshold=Decimal("0"),
            parameters={"program": program.payload, "text": program.text},
        ),
        backtest=BacktestSpec(
            costs=costs_for(the_desk).engine_costs(),
            allow_short=program.uses_short,
            warmup_bars=program.warmup,
        ),
        seed=seed,
        metrics=(
            "total_return",
            "sharpe",
            "max_drawdown",
            "n_trades",
            "turnover",
            "cost_drag",
        ),
    )


def baseline_spec(
    kind: str,
    *,
    desk: Desk | str,
    bars: int,
    like: ExperimentSpec,
) -> ExperimentSpec:
    """A reference run over exactly the bars the authored rule traded.

    ``like`` supplies the warm-up and the costs, so the comparison is between
    two rules on the same window paying the same charges.
    """
    if kind not in BASELINES:
        raise ValueError(f"{kind} is not a baseline; baselines are {list(BASELINES)}")
    the_desk = desk if isinstance(desk, Desk) else Desk(desk)
    return ExperimentSpec(
        engine="local",
        universe=UniverseSpec(
            desk=the_desk.value,
            symbols=(),
            point_in_time=True,
            selection="point_in_time",
        ),
        data=DataSpec(
            source=like.data.source,
            bars=bars,
            interval=like.data.interval,
        ),
        signal=SignalSpec(kind=kind, lookback=like.signal.lookback),
        backtest=like.backtest,
        seed=like.seed,
        metrics=like.metrics,
    )
