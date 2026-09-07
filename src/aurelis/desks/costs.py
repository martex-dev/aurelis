"""What trading actually costs, per asset class.

`docs/02-organization.md` says a desk without a realistic cost model cannot be
opened at all, because a backtest without one is not evidence. This module is
that model, and it is the part of a desk that is least interchangeable: the
things you pay to trade an S&P future and the things you pay to trade a
memecoin have almost nothing in common.

Four kinds of cost, and keeping them apart matters because they behave
differently:

**Per-trade** — commission, exchange fee, the half-spread you cross. Scales
with turnover. This is what the engine's ``CostModel`` already charges.

**Per-holding-period** — funding on a perpetual, borrow on a short, the roll on
a future rolling down a contango curve. Scales with *time held*, not with
turnover, so a low-turnover strategy does not escape it. A cost model that
folded this into the spread would flatter every slow strategy on a carry desk.

**Per-contract** — options and futures charge in units, not basis points. On a
cheap option a fixed per-contract fee can be a larger cost than the spread, and
expressing it in bps of notional hides that entirely.

**Impact** — what your own size does to the price. Declared as the size at
which impact becomes material rather than as a coefficient, because a
coefficient invites a precision nobody has.

The numbers below are **stated defaults, not measured facts about any venue**.
They are conservative order-of-magnitude figures for a liquid instrument on
each desk, they carry the source of the assumption in ``basis``, and every
research artifact records the model it charged. A desk that later measures its
own realised costs replaces these, and the backtest-live gap from M9 is exactly
the instrument that would catch them being wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.engines.spec import CostModel
from aurelis.org.desks import Desk

__all__ = ["DESK_COSTS", "DeskCostModel", "Liquidity", "costs_for"]

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class Liquidity:
    """How much can be traded before the price answers back."""

    typical_spread_bps: Decimal
    material_size_usd: Decimal
    """Order size at which market impact stops being negligible. A cap on what
    any backtest on this desk may claim to have traded."""

    settlement_days: int
    shortable: bool
    borrow_bps_annual: Decimal = _ZERO

    def as_payload(self) -> dict[str, Any]:
        return {
            "typical_spread_bps": str(self.typical_spread_bps),
            "material_size_usd": str(self.material_size_usd),
            "settlement_days": self.settlement_days,
            "shortable": self.shortable,
            "borrow_bps_annual": str(self.borrow_bps_annual),
        }


@dataclass(frozen=True, slots=True)
class DeskCostModel:
    """One desk's cost assumptions, and where they came from."""

    desk: Desk
    commission_bps: Decimal
    spread_bps: Decimal
    slippage_bps: Decimal

    carry_bps_annual: Decimal = _ZERO
    """Funding, borrow or roll. Charged on *time held*, so a slow strategy
    pays it in full and a fast one barely notices — the opposite of how
    per-trade costs fall."""

    per_contract_usd: Decimal = _ZERO
    """Options and futures charge in units. Folding this into basis points
    would hide that on a cheap option it can exceed the spread."""

    contract_multiplier: int = 1
    liquidity: Liquidity = Liquidity(Decimal(5), Decimal(100_000), 0, True)
    basis: str = ""
    """Where the assumption came from. A cost model with no stated basis is a
    number somebody typed."""

    @property
    def round_trip_bps(self) -> Decimal:
        """What one complete in-and-out costs, before carry."""
        return (self.commission_bps + self.spread_bps + self.slippage_bps) * Decimal(2)

    def engine_costs(self) -> CostModel:
        """The per-trade part, in the shape the engine charges.

        Carry and per-contract fees are **not** folded in. The engine charges
        on turnover, and a cost that scales with time held or with unit count
        would be silently misattributed if it were expressed as a fee per
        trade. They are reported separately and applied where they belong.
        """
        return CostModel(
            fee_bps=self.commission_bps,
            spread_bps=self.spread_bps,
            slippage_bps=self.slippage_bps,
        )

    def carry_for(self, bars_held: int, periods_per_year: int) -> Decimal:
        """The holding cost of staying in for ``bars_held`` bars.

        Zero on a desk with no carry, and never negative: a desk that *earned*
        carry would be a different model, and pretending a cost is a revenue is
        how a carry trade backtests beautifully.
        """
        if not self.carry_bps_annual or bars_held <= 0 or periods_per_year <= 0:
            return _ZERO
        fraction = Decimal(bars_held) / Decimal(periods_per_year)
        return (self.carry_bps_annual * fraction / Decimal(10_000)).quantize(
            Decimal("0.00000001")
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "desk": self.desk.value,
            "commission_bps": str(self.commission_bps),
            "spread_bps": str(self.spread_bps),
            "slippage_bps": str(self.slippage_bps),
            "round_trip_bps": str(self.round_trip_bps),
            "carry_bps_annual": str(self.carry_bps_annual),
            "per_contract_usd": str(self.per_contract_usd),
            "contract_multiplier": self.contract_multiplier,
            "liquidity": self.liquidity.as_payload(),
            "basis": self.basis,
        }

    def describe(self) -> str:
        carry = (
            f", carry {self.carry_bps_annual}bps/yr" if self.carry_bps_annual else ""
        )
        contract = (
            f", ${self.per_contract_usd}/contract" if self.per_contract_usd else ""
        )
        return f"{self.round_trip_bps}bps round trip{carry}{contract}"


DESK_COSTS: dict[Desk, DeskCostModel] = {
    model.desk: model
    for model in (
        DeskCostModel(
            Desk.CRYPTO,
            commission_bps=Decimal(10),
            spread_bps=Decimal(5),
            slippage_bps=Decimal(5),
            carry_bps_annual=Decimal(1000),
            liquidity=Liquidity(
                typical_spread_bps=Decimal(5),
                material_size_usd=Decimal(500_000),
                settlement_days=0,
                shortable=True,
            ),
            basis=(
                "Taker fees on a major centralised venue, and perpetual "
                "funding at roughly 10% annualised over a long-biased period. "
                "Funding is the cost that turns a profitable-looking perpetual "
                "carry into a losing one, and it is charged on time held."
            ),
        ),
        DeskCostModel(
            Desk.EQUITIES,
            commission_bps=Decimal(1),
            spread_bps=Decimal(3),
            slippage_bps=Decimal(4),
            carry_bps_annual=Decimal(50),
            liquidity=Liquidity(
                typical_spread_bps=Decimal(3),
                material_size_usd=Decimal(2_000_000),
                settlement_days=1,
                shortable=True,
                borrow_bps_annual=Decimal(50),
            ),
            basis=(
                "Institutional commission on a large-cap US name, a few basis "
                "points of spread, and general-collateral borrow for the short "
                "side. Hard-to-borrow names cost an order of magnitude more, "
                "which is why a short book needs a per-name borrow rate before "
                "this desk trades one."
            ),
        ),
        DeskCostModel(
            Desk.OPTIONS,
            commission_bps=Decimal(2),
            spread_bps=Decimal(80),
            slippage_bps=Decimal(30),
            per_contract_usd=Decimal("0.65"),
            contract_multiplier=100,
            liquidity=Liquidity(
                typical_spread_bps=Decimal(80),
                material_size_usd=Decimal(250_000),
                settlement_days=1,
                shortable=True,
            ),
            basis=(
                "The widest spreads of any desk by an order of magnitude: 80bps "
                "on a liquid front-month strike, far worse away from the money. "
                "Options strategies that look profitable at equity-like costs "
                "are the single most common false discovery in this asset "
                "class, and the per-contract fee is charged on top because on a "
                "cheap option it exceeds the spread."
            ),
        ),
        DeskCostModel(
            Desk.FUTURES,
            commission_bps=Decimal("0.5"),
            spread_bps=Decimal(1),
            slippage_bps=Decimal(2),
            carry_bps_annual=Decimal(30),
            per_contract_usd=Decimal("2.50"),
            contract_multiplier=50,
            liquidity=Liquidity(
                typical_spread_bps=Decimal(1),
                material_size_usd=Decimal(10_000_000),
                settlement_days=0,
                shortable=True,
            ),
            basis=(
                "The cheapest desk to trade and the one with the most hidden "
                "cost: spreads are a basis point, and the roll is charged four "
                "times a year whether or not the position moved. A continuous "
                "contract that ignores the roll is not a price series."
            ),
        ),
        DeskCostModel(
            Desk.COMMODITIES,
            commission_bps=Decimal("0.5"),
            spread_bps=Decimal(4),
            slippage_bps=Decimal(6),
            carry_bps_annual=Decimal(400),
            per_contract_usd=Decimal("2.50"),
            contract_multiplier=1000,
            liquidity=Liquidity(
                typical_spread_bps=Decimal(4),
                material_size_usd=Decimal(2_000_000),
                settlement_days=0,
                shortable=True,
            ),
            basis=(
                "Same venue as futures and a completely different carry. A "
                "contango curve in energy can cost several percent a year to "
                "hold, which is why a long commodity strategy has to clear a "
                "hurdle before it has found anything at all."
            ),
        ),
        DeskCostModel(
            Desk.FX,
            commission_bps=Decimal("0.2"),
            spread_bps=Decimal("0.8"),
            slippage_bps=Decimal(1),
            carry_bps_annual=Decimal(150),
            liquidity=Liquidity(
                typical_spread_bps=Decimal("0.8"),
                material_size_usd=Decimal(20_000_000),
                settlement_days=2,
                shortable=True,
            ),
            basis=(
                "Sub-basis-point spreads on a major pair, and a carry that is "
                "the entire strategy rather than a cost: the rate differential "
                "is charged here as a holding cost so that a carry trade has to "
                "earn it back on the price, which is the honest way to test "
                "whether the trade is anything more than the differential."
            ),
        ),
        DeskCostModel(
            Desk.MEMECOIN,
            commission_bps=Decimal(30),
            spread_bps=Decimal(150),
            slippage_bps=Decimal(200),
            liquidity=Liquidity(
                typical_spread_bps=Decimal(150),
                material_size_usd=Decimal(5_000),
                settlement_days=0,
                shortable=False,
            ),
            basis=(
                "By far the most expensive desk, and the one where the cost "
                "model does most of the work. Round-trip cost is nearly 8%, "
                "material size is five thousand dollars, and there is no short "
                "side. A memecoin strategy that survives these numbers is "
                "worth looking at; almost none do, and that is the finding."
            ),
        ),
    )
}


def costs_for(desk: Desk | str) -> DeskCostModel:
    """The cost model this desk trades under."""
    key = Desk(desk) if isinstance(desk, str) else desk
    try:
        return DESK_COSTS[key]
    except KeyError:  # pragma: no cover - every registered desk has one
        raise KeyError(
            f"desk {key.value!r} has no cost model, so it cannot be opened. A "
            "backtest without a realistic cost model is not evidence."
        ) from None
