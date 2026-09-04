"""Market Intelligence: what the company has observed.

Observations are bitemporal facts with a source and a data digest, never
conclusions. Interpretation is a Finding, and Findings arrive with the research
lifecycle at M4.
"""

from aurelis.intel.briefing import TASK_KIND, run_briefing
from aurelis.intel.features import describe_bars
from aurelis.intel.sources import Bar, FixtureSource, MarketDataSource, snapshot_for
from aurelis.intel.tables import MarketObservation, ObservationKind

__all__ = [
    "TASK_KIND",
    "Bar",
    "FixtureSource",
    "MarketDataSource",
    "MarketObservation",
    "ObservationKind",
    "describe_bars",
    "run_briefing",
    "snapshot_for",
]
