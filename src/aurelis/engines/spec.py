"""Experiment specifications.

A specification is the complete, canonical description of a piece of
computation: which instruments, which window, which rule, which costs, which
seed. It is hashed, and that hash is what a preregistration locks.

Three properties make it work as a preregistration:

**Total.** Everything that could change the answer is in the spec. If a knob
lives outside it, the spec no longer identifies the computation and the lock
protects nothing.

**Canonical.** Two specs describing the same computation hash identically,
whatever order their fields were built in — that is :mod:`aurelis.core.canonical`
doing its job, and it is why the same experiment run twice deduplicates instead
of costing twice.

**Float-free.** Every number is a ``Decimal`` or a string. A cost model
expressed in binary floats would hash differently on two machines and the lock
would be worthless.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from aurelis.core.canonical import sha256_of

__all__ = [
    "BacktestSpec",
    "CostModel",
    "DataSpec",
    "ExperimentSpec",
    "SignalSpec",
    "UniverseSpec",
]


@dataclass(frozen=True, slots=True)
class UniverseSpec:
    """Which instruments, and how they were chosen.

    ``point_in_time`` is carried even though M4's fixture universe is fixed,
    because the field is where survivorship bias gets caught at M5. A universe
    chosen with hindsight and one chosen as of the start date are different
    experiments, and the spec has to be able to say which this was.
    """

    desk: str
    symbols: tuple[str, ...]
    point_in_time: bool = False
    selection: str = "fixed"


@dataclass(frozen=True, slots=True)
class DataSpec:
    """Which observations, over which window."""

    source: str
    bars: int
    interval: str = "1h"
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True, slots=True)
class SignalSpec:
    """The rule under test.

    ``kind`` names a **registered operation**, never free-form code. The space
    of expressible experiments is small, written by hand and unit-tested, which
    is what makes a result reproducible by someone who did not watch it run.
    """

    kind: str
    lookback: int = 24
    threshold: Decimal = Decimal("0")
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CostModel:
    """What trading is assumed to cost.

    Never optional and never zero by default. A backtest without costs is not
    evidence, and a default of zero would let one be produced by omission.
    """

    fee_bps: Decimal = Decimal("10")
    spread_bps: Decimal = Decimal("5")
    slippage_bps: Decimal = Decimal("5")

    @property
    def round_trip_bps(self) -> Decimal:
        return (self.fee_bps + self.spread_bps + self.slippage_bps) * Decimal(2)


@dataclass(frozen=True, slots=True)
class BacktestSpec:
    """How the rule is evaluated."""

    initial_cash: Decimal = Decimal("10000")
    allow_short: bool = False
    costs: CostModel = field(default_factory=CostModel)
    warmup_bars: int = 0


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """The whole computation, in one hashable object."""

    engine: str
    universe: UniverseSpec
    data: DataSpec
    signal: SignalSpec
    backtest: BacktestSpec = field(default_factory=BacktestSpec)
    seed: int = 0
    metrics: tuple[str, ...] = ("total_return", "sharpe", "max_drawdown")

    def as_payload(self) -> dict[str, Any]:
        """Canonical, plain-JSON dictionary form. What gets hashed and stored.

        Decimals become their exact strings. Two reasons, and both matter:
        a JSON column cannot hold a Decimal, and a payload that round-trips
        through the database must hash to the same value it did before it was
        stored — otherwise a registration's digest would change simply by
        being written down.
        """
        payload: dict[str, Any] = _plain(asdict(self))
        return payload

    def digest(self) -> str:
        """The spec hash. What a preregistration locks."""
        return sha256_of(self.as_payload())

    def describe(self) -> str:
        return (
            f"{self.engine}:{self.signal.kind}(lookback={self.signal.lookback}) "
            f"over {self.data.bars} {self.data.interval} bars of "
            f"{','.join(self.universe.symbols)} seed={self.seed}"
        )


def _plain(value: Any) -> Any:
    """Recursively render a structure as plain JSON types, exactly.

    ``Decimal`` becomes its own string rather than a float: the whole point of
    using Decimal is that the value survives, and passing it through a binary
    float on the way to storage would throw that away at the last step.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
