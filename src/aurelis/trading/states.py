"""The trading vocabulary.

One member is missing on purpose and its absence is the milestone's most
important property: :class:`BrokerKind` has no ``LIVE``.

`CLAUDE.md` §13 asks for a ``LiveBroker`` "disabled by default". ADR-0006
records why Aurelis holds a stronger line: disabled-by-default is one flag from
enabled, and flags get flipped at three in the morning by somebody who has
stopped reading. There is no live adapter, no enum member naming one, and no
code path that could resolve one — so enabling real money is a schema change
and a review rather than a configuration edit.

The other distinction worth stating is between a **fill** and an **expectation**.
An order carries what the strategy asked for; a fill carries what actually
happened; and the difference between them is slippage, which is the cheapest
honest measurement the company makes about its own assumptions.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "BrokerKind",
    "OrderSide",
    "OrderStatus",
    "TERMINAL_ORDER_STATUSES",
]


class BrokerKind(StrEnum):
    """Where an order is executed.

    **There is no LIVE member.** A test asserts it, and another asserts that no
    Aurelis module imports martex-quant's MT5 adapter. The gates in that
    project stay exactly where they are; Aurelis creates no new path to them.
    """

    BACKTEST = "backtest"
    """The engine's simulated fills, over historical bars."""

    SIMULATION = "simulation"
    """Scenario replay — a constructed sequence, used to test how the company
    behaves rather than how a market did."""

    PAPER = "paper"
    """Forward testing on simulated capital against real, current prices. The
    only mode where reality gets a vote."""


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    """The broker refused it. A recorded outcome, not an exception — a rejected
    order is information about the venue or the instruction."""

    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_ORDER_STATUSES = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    }
)
