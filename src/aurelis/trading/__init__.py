"""Trading operations: paper only, and the chain that makes it so.

The execution boundary is the point of this package. An order requires an
approval; an approval requires a permitting risk assessment of its own
proposal; and both requirements are foreign keys with triggers behind them, so
the chain is a shape the database accepts rather than a convention the code
follows.

**There is no live broker.** Not disabled — absent: no adapter, no
:class:`~aurelis.trading.states.BrokerKind` member, no registry entry, and
:func:`~aurelis.trading.brokers.resolve` refuses the string with an explanation
rather than a ``KeyError``. A test asserts that no Aurelis module imports
martex-quant's MT5 adapter. Enabling real money is a separate, separately
reviewed project (ADR-0006).

The measurement this milestone exists for is the **backtest-live gap**: what
the backtest claimed against what paper actually produced, per metric, citing
the artifact digest of the number that justified deployment. It is the only
place in the company where a claim is checked by something the company does not
control, and it is tracked as a company competence — how wrong our backtests
tend to be is a fact about us, not about any one strategy.
"""

from aurelis.trading.brokers import (
    BacktestBroker,
    BrokerAdapter,
    ExecutionRequest,
    ExecutionResult,
    PaperBroker,
    SimulationBroker,
    adapters,
    resolve,
)
from aurelis.trading.cycle import (
    GAP_QUESTION,
    CycleOutcome,
    PaperCycle,
    gap_outcome,
    record_gap_forecast,
)
from aurelis.trading.execution import Executed, Execution
from aurelis.trading.posttrade import Gap, PostTrade, Slippage
from aurelis.trading.states import BrokerKind, OrderSide, OrderStatus
from aurelis.trading.tables import Fill, GapMeasurement, Order, Position, PostTradeReport
from aurelis.trading.triggers import (
    expected_trading_trigger_names,
    install_trading_invariants,
    verify_trading_invariants,
)

__all__ = [
    "GAP_QUESTION",
    "BacktestBroker",
    "BrokerAdapter",
    "BrokerKind",
    "CycleOutcome",
    "Executed",
    "Execution",
    "ExecutionRequest",
    "ExecutionResult",
    "Fill",
    "Gap",
    "GapMeasurement",
    "Order",
    "OrderSide",
    "OrderStatus",
    "PaperBroker",
    "PaperCycle",
    "Position",
    "PostTrade",
    "PostTradeReport",
    "SimulationBroker",
    "Slippage",
    "adapters",
    "expected_trading_trigger_names",
    "gap_outcome",
    "install_trading_invariants",
    "record_gap_forecast",
    "resolve",
    "verify_trading_invariants",
]
