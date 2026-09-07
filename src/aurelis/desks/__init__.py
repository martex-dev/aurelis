"""The seven market desks: what each one costs, when it trades, what bounds it.

A desk is the company's second organisational dimension, and it is more than a
label on an agent. It is a **clock**, a **cost model**, a **liquidity ceiling**
and a set of **risk limits**, and those four differ enough between asset
classes that sharing them would be wrong everywhere.

The clock is the one that had been quietly missing. The engine reported Sharpe
as ``unit="per_bar"``, which was honest and useless: a per-bar Sharpe on hourly
crypto bars and one on daily equity bars are different quantities wearing the
same name, and an archive that ranked them together would rank by sampling
frequency. `comparability` is where that is fixed, and where a comparison that
cannot be made is refused rather than fudged.

**Nothing here is live market data.** Every desk M12 opens runs on fixtures --
deterministic, offline, shaped like the desk but not a market -- and the
readiness check records that as `PROVISIONAL` rather than letting it read as a
pass.
"""

from __future__ import annotations

from aurelis.desks.calendars import CALENDARS, TradingCalendar, calendar_for, calendar_named
from aurelis.desks.comparability import (
    METRIC_SCALING,
    Comparable,
    Incomparable,
    Scaling,
    annualise,
    compare,
)
from aurelis.desks.costs import DESK_COSTS, DeskCostModel, Liquidity, costs_for
from aurelis.desks.limits import DeskLimits, limits_for
from aurelis.desks.opening import Desks, OpenedDesk
from aurelis.desks.power import PowerRequirement, bars_for_span, required_observations
from aurelis.desks.readiness import (
    CHECKS,
    Assessment,
    Readiness,
    ReadinessItem,
    assess,
)
from aurelis.desks.sources import (
    DESK_FIXTURES,
    DeskFixture,
    DeskUniverse,
    fixture_for,
    live_feed_status,
)

__all__ = [
    "CALENDARS",
    "CHECKS",
    "DESK_COSTS",
    "DESK_FIXTURES",
    "METRIC_SCALING",
    "Assessment",
    "Comparable",
    "DeskCostModel",
    "DeskFixture",
    "DeskLimits",
    "DeskUniverse",
    "Desks",
    "Incomparable",
    "OpenedDesk",
    "PowerRequirement",
    "Liquidity",
    "Readiness",
    "ReadinessItem",
    "Scaling",
    "TradingCalendar",
    "annualise",
    "assess",
    "bars_for_span",
    "calendar_for",
    "calendar_named",
    "compare",
    "costs_for",
    "fixture_for",
    "limits_for",
    "live_feed_status",
    "required_observations",
]
