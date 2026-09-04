"""Engines: the only things in Aurelis that produce a number.

No agent writes a measurement. Every metric comes from an engine and carries
the digest of the data it was computed from, the code version that produced
it, and the seed it ran under.
"""

from aurelis.engines.local import SIGNALS, LocalEngine
from aurelis.engines.martex import MartexEngine, MartexStatistics, deflated_sharpe
from aurelis.engines.protocol import (
    EngineCapabilities,
    EngineUnavailable,
    Metric,
    MetricSet,
    ResearchEngine,
    RunArtifact,
    UnsupportedMetric,
)
from aurelis.engines.registry import available_engines, engine_for, engine_named, survey
from aurelis.engines.spec import (
    BacktestSpec,
    CostModel,
    DataSpec,
    ExperimentSpec,
    SignalSpec,
    UniverseSpec,
)

__all__ = [
    "SIGNALS",
    "BacktestSpec",
    "CostModel",
    "DataSpec",
    "EngineCapabilities",
    "EngineUnavailable",
    "ExperimentSpec",
    "LocalEngine",
    "MartexEngine",
    "MartexStatistics",
    "Metric",
    "MetricSet",
    "ResearchEngine",
    "RunArtifact",
    "SignalSpec",
    "UniverseSpec",
    "UnsupportedMetric",
    "available_engines",
    "deflated_sharpe",
    "engine_for",
    "engine_named",
    "survey",
]
