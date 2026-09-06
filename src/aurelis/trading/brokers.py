"""Broker adapters. Three exist; the fourth is deliberately absent.

`CLAUDE.md` §13 sketches ``BrokerAdapter`` with ``PaperBroker``,
``BacktestBroker`` and a ``LiveBroker`` "disabled by default". ADR-0006 records
why Aurelis goes further: **there is no live adapter here at all.** Not written,
not registered, not reachable. ``BrokerKind`` has no member naming one, the
registry cannot resolve one, and :func:`resolve` refuses the string ``"live"``
with an explanation rather than a ``KeyError``, so an operator who tries learns
why instead of assuming a typo.

The three that do exist differ in what they know:

``BacktestBroker`` fills at the price the strategy expected, plus the cost
model the strategy declared. It cannot surprise anyone — which is the point. It
is the baseline the other two are measured against.

``SimulationBroker`` replays a scripted sequence of prices and rejections. Its
value is testing how the *company* behaves — what happens when a fill comes
back worse, or an order is rejected — rather than how a market did.

``PaperBroker`` fills against the current observed price with a modelled
impact. It is the only adapter whose output the company did not choose, and so
the only one whose gap against the backtest means anything.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from aurelis.core.errors import ConfigurationError
from aurelis.trading.states import BrokerKind, OrderSide, OrderStatus

__all__ = [
    "BacktestBroker",
    "BrokerAdapter",
    "ExecutionRequest",
    "ExecutionResult",
    "PaperBroker",
    "SimulationBroker",
    "adapters",
    "resolve",
]


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """What is being asked of a broker."""

    symbol: str
    side: OrderSide
    quantity: Decimal
    expected_price: Decimal
    fee_bps: Decimal = Decimal("10")
    spread_bps: Decimal = Decimal("5")
    impact_bps: Decimal = Decimal("0")
    limit_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """What came back. A rejection is a result, not an exception."""

    status: OrderStatus
    filled_quantity: Decimal
    price: Decimal
    fee: Decimal
    detail: str
    rejection_reason: str = ""

    @property
    def filled(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)


class BrokerAdapter(Protocol):
    """The execution boundary.

    Deliberately tiny. Everything a broker needs is in the request, and
    everything the company learns is in the result — so a new adapter cannot
    quietly acquire access to the portfolio, the strategy or the ledger.
    """

    @property
    def kind(self) -> BrokerKind:
        """Which of the three this is. Read-only, so a frozen adapter
        satisfies the protocol and nothing can retype an adapter at runtime."""
        ...

    def submit(
        self, request: ExecutionRequest, *, at: dt.datetime
    ) -> ExecutionResult: ...


def _signed(side: OrderSide) -> Decimal:
    return Decimal(1) if side is OrderSide.BUY else Decimal(-1)


@dataclass(frozen=True, slots=True)
class BacktestBroker:
    """Fills at the expected price plus the declared cost model.

    Incapable of surprising anyone, which is exactly its job: it is the
    baseline. If a backtest and a paper run disagree, this adapter is the half
    that contains no information about the world.
    """

    kind: BrokerKind = BrokerKind.BACKTEST

    def submit(self, request: ExecutionRequest, *, at: dt.datetime) -> ExecutionResult:
        half_spread = request.expected_price * request.spread_bps / Decimal(20_000)
        price = request.expected_price + _signed(request.side) * half_spread
        fee = price * request.quantity * request.fee_bps / Decimal(10_000)
        return ExecutionResult(
            status=OrderStatus.FILLED,
            filled_quantity=request.quantity,
            price=price.quantize(Decimal("0.00000001")),
            fee=fee.quantize(Decimal("0.00000001")),
            detail=f"modelled fill at {request.spread_bps}bps spread, {at.isoformat()}",
        )


@dataclass(slots=True)
class SimulationBroker:
    """Replays a scripted sequence of outcomes.

    Used to test how the company reacts — to a bad fill, a rejection, a partial
    — rather than how a market behaved. The script is exhausted in order and
    then repeats its last entry, so a scenario cannot silently run past its own
    definition into invented behaviour.
    """

    script: Sequence[ExecutionResult]
    kind: BrokerKind = BrokerKind.SIMULATION
    _index: int = field(default=0, repr=False)

    def submit(self, request: ExecutionRequest, *, at: dt.datetime) -> ExecutionResult:
        if not self.script:
            raise ConfigurationError(
                "a SimulationBroker with an empty script has nothing to replay; "
                "a scenario that invented its own fills would not be a scenario"
            )
        step = self.script[min(self._index, len(self.script) - 1)]
        self._index += 1
        return step


@dataclass(frozen=True, slots=True)
class PaperBroker:
    """Forward testing on simulated capital against observed prices.

    The one adapter whose output the company did not choose. ``mark`` is the
    current observed price supplied by the caller — the broker does not fetch
    it, because a broker that reached for data would be a second, unversioned
    path to the market.
    """

    marks: dict[str, Decimal] = field(default_factory=dict)
    kind: BrokerKind = BrokerKind.PAPER

    def submit(self, request: ExecutionRequest, *, at: dt.datetime) -> ExecutionResult:
        mark = self.marks.get(request.symbol)
        if mark is None:
            return ExecutionResult(
                status=OrderStatus.REJECTED,
                filled_quantity=Decimal(0),
                price=Decimal(0),
                fee=Decimal(0),
                detail="no observed price",
                rejection_reason=(
                    f"no mark for {request.symbol}; a paper fill against an "
                    "assumed price would be a backtest wearing a paper label"
                ),
            )

        drift = request.impact_bps + request.spread_bps / Decimal(2)
        price = mark + _signed(request.side) * mark * drift / Decimal(10_000)

        if request.limit_price is not None:
            crossed = (
                price <= request.limit_price
                if request.side is OrderSide.BUY
                else price >= request.limit_price
            )
            if not crossed:
                return ExecutionResult(
                    status=OrderStatus.EXPIRED,
                    filled_quantity=Decimal(0),
                    price=Decimal(0),
                    fee=Decimal(0),
                    detail=f"limit {request.limit_price} not crossed at {price}",
                )

        fee = price * request.quantity * request.fee_bps / Decimal(10_000)
        return ExecutionResult(
            status=OrderStatus.FILLED,
            filled_quantity=request.quantity,
            price=price.quantize(Decimal("0.00000001")),
            fee=fee.quantize(Decimal("0.00000001")),
            detail=f"paper fill against mark {mark} at {at.isoformat()}",
        )


def adapters(
    *,
    marks: dict[str, Decimal] | None = None,
    script: Sequence[ExecutionResult] | None = None,
) -> dict[BrokerKind, BrokerAdapter]:
    """Build the three adapters. There is no fourth."""
    built: dict[BrokerKind, BrokerAdapter] = {
        BrokerKind.BACKTEST: BacktestBroker(),
        BrokerKind.PAPER: PaperBroker(dict(marks or {})),
    }
    if script is not None:
        built[BrokerKind.SIMULATION] = SimulationBroker(list(script))
    return built


def resolve(name: str, available: dict[BrokerKind, BrokerAdapter]) -> BrokerAdapter:
    """Look up an adapter by name, refusing ``live`` with an explanation.

    A ``KeyError`` would read as a typo. This reads as a decision, which is
    what it is: enabling real-money execution is a separate, separately-scoped
    project, and the absence here is deliberate rather than unfinished.
    """
    if name.lower() in ("live", "real", "production"):
        raise ConfigurationError(
            "there is no live broker in Aurelis. Not disabled — absent: no "
            "adapter, no BrokerKind member, and no code path that could reach "
            "one. Real-money execution is a separate project with its own "
            "review (ADR-0006)"
        )
    try:
        kind = BrokerKind(name)
    except ValueError:
        raise ConfigurationError(
            f"unknown broker {name!r}; Aurelis has "
            f"{', '.join(k.value for k in BrokerKind)}"
        ) from None
    adapter = available.get(kind)
    if adapter is None:
        raise ConfigurationError(
            f"the {kind.value} broker is not configured in this runtime"
        )
    return adapter
