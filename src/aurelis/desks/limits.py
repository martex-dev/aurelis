"""Risk limits per desk, set from what the desk actually is.

A single company-wide leverage cap would be wrong in both directions: it would
be reckless on memecoins and pointlessly restrictive on FX, where a major pair
moves less in a month than a micro-cap token does in an afternoon. So the
limits are derived from the desk's own volatility, liquidity and cost — and
derived rather than typed, so that changing a desk's liquidity assumption moves
its limits with it instead of leaving them stale.

Two of the bounds are the ones that actually bite.

**``max_position_usd``** is the desk's material size, not a policy number. It
is the point at which the cost model stops being believable, so it is the
largest position any backtest on the desk may claim — a strategy that needs
more than the market bears has not found an edge, it has found a number.

**``min_round_trips_to_break_even``** is the cost hurdle stated as a fact about
the desk. On memecoins, a round trip costs nearly 8%, so a strategy trading
weekly has to make 8% a week before it has made anything. Reading that off the
cost model is more use than any leverage cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.desks.costs import costs_for
from aurelis.org.desks import Desk

__all__ = ["DeskLimits", "limits_for"]


@dataclass(frozen=True, slots=True)
class DeskLimits:
    """What bounds trading on one desk."""

    desk: Desk
    max_gross_leverage: Decimal
    max_single_name_weight: Decimal
    max_position_usd: Decimal
    max_drawdown: Decimal
    """Beyond this a strategy on this desk is suspended, not reviewed."""

    round_trip_cost: Decimal
    shortable: bool
    rationale: str

    @property
    def cost_hurdle_bps(self) -> Decimal:
        """What a round trip costs, in basis points. The hurdle to clear."""
        return self.round_trip_cost

    def as_payload(self) -> dict[str, Any]:
        return {
            "desk": self.desk.value,
            "max_gross_leverage": str(self.max_gross_leverage),
            "max_single_name_weight": str(self.max_single_name_weight),
            "max_position_usd": str(self.max_position_usd),
            "max_drawdown": str(self.max_drawdown),
            "round_trip_cost_bps": str(self.round_trip_cost),
            "shortable": self.shortable,
            "rationale": self.rationale,
        }

    def describe(self) -> str:
        return (
            f"{self.max_gross_leverage}x gross, "
            f"{self.max_single_name_weight} per name, "
            f"${self.max_position_usd} max position, "
            f"{self.max_drawdown} drawdown"
        )


#: Leverage and concentration caps, per desk. Not derived: these are policy,
#: and policy should be visible rather than emergent from a formula.
_POLICY: dict[Desk, tuple[str, str, str, str]] = {
    #                     gross   per-name  drawdown  rationale
    Desk.CRYPTO: (
        "2",
        "0.40",
        "0.25",
        "Deep enough to size into, volatile enough that two turns is plenty, "
        "and funding is charged on every hour held.",
    ),
    Desk.EQUITIES: (
        "2",
        "0.15",
        "0.20",
        "The most diversifiable desk, so concentration is capped hardest. "
        "Borrow makes the short side cost real money.",
    ),
    Desk.OPTIONS: (
        "1",
        "0.10",
        "0.30",
        "No leverage on top of an instrument that is already leveraged. The "
        "drawdown bound is wider because a defined-risk position can lose all "
        "of a small allocation without anything having gone wrong.",
    ),
    Desk.FUTURES: (
        "3",
        "0.35",
        "0.20",
        "The cheapest and deepest desk, so it carries the highest gross. The "
        "roll is charged four times a year whether or not the position moved.",
    ),
    Desk.COMMODITIES: (
        "2",
        "0.30",
        "0.25",
        "Same venue as futures and a carry an order of magnitude larger; a "
        "long book pays several percent a year to exist.",
    ),
    Desk.FX: (
        "5",
        "0.40",
        "0.15",
        "The highest gross and the tightest drawdown: a major pair barely "
        "moves, so an FX strategy that draws down 15% has broken rather than "
        "had a bad month.",
    ),
    Desk.MEMECOIN: (
        "1",
        "0.05",
        "0.50",
        "No leverage, no shorting, and five percent per name — because most "
        "of the universe goes to zero and the cost of a round trip is nearly "
        "eight percent. The drawdown bound is wide because anything tighter "
        "would suspend every strategy in its first week, which would hide the "
        "finding rather than produce it.",
    ),
}


def limits_for(desk: Desk | str) -> DeskLimits:
    """The bounds this desk trades under, read off its own cost model."""
    key = Desk(desk) if isinstance(desk, str) else desk
    gross, per_name, drawdown, rationale = _POLICY[key]
    model = costs_for(key)
    return DeskLimits(
        desk=key,
        max_gross_leverage=Decimal(gross),
        max_single_name_weight=Decimal(per_name),
        # Not a policy number: the size at which this desk's own cost model
        # stops being believable. A backtest may not claim to have traded more.
        max_position_usd=model.liquidity.material_size_usd,
        max_drawdown=Decimal(drawdown),
        round_trip_cost=model.round_trip_bps,
        shortable=model.liquidity.shortable,
        rationale=rationale,
    )
