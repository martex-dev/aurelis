"""What an engine is, and what it promises.

An engine is the only thing in Aurelis that produces a number. No agent writes
a measurement; engines do, and every metric they return carries the digest of
the data it was computed from.

``capabilities()`` is the part that keeps the abstraction honest. The options
engine will compute greeks and the crypto engine will not, and an agent asking
for something an engine cannot do must get a **typed refusal** rather than a
plausible-looking wrong number. An engine that silently returned zero for a
metric it does not support would be worse than one that did not exist.

Metrics carry an interval, not just a point. That is not decoration: the
verdict rule needs to distinguish "no effect" from "we could not tell", and
those two are the same point estimate with different interval widths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from aurelis.core.canonical import sha256_of
from aurelis.engines.spec import ExperimentSpec

__all__ = [
    "EngineCapabilities",
    "EngineUnavailable",
    "Metric",
    "MetricSet",
    "ResearchEngine",
    "RunArtifact",
    "UnsupportedMetric",
]


class EngineUnavailable(RuntimeError):
    """The engine is not installed, or its workspace is missing."""


class UnsupportedMetric(KeyError):
    """A metric this engine cannot compute.

    Raised rather than returning a default, because a default is a number and
    a number that came from nowhere is exactly what the whole design exists to
    prevent.
    """


@dataclass(frozen=True, slots=True)
class Metric:
    """One measured quantity, with its uncertainty and its provenance.

    ``low`` and ``high`` are the confidence bounds where the engine can
    produce them, and ``None`` where it genuinely cannot — not zero, and not
    the point estimate repeated. A missing interval makes a claim
    ``UNDERPOWERED`` by the verdict rule, which is the honest consequence.
    """

    name: str
    value: Decimal
    low: Decimal | None = None
    high: Decimal | None = None
    unit: str = ""
    method: str = ""
    """How it was computed, e.g. ``martex.probabilistic_sharpe_ratio@1.0.1``.
    A metric that cannot say how it was produced cannot be reproduced."""

    @property
    def has_interval(self) -> bool:
        return self.low is not None and self.high is not None

    @property
    def width(self) -> Decimal | None:
        if self.low is None or self.high is None:
            return None
        return self.high - self.low

    def as_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "low": self.low,
            "high": self.high,
            "unit": self.unit,
            "method": self.method,
        }


@dataclass(frozen=True, slots=True)
class MetricSet:
    """Everything one run measured."""

    metrics: tuple[Metric, ...]

    def get(self, name: str) -> Metric:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        raise UnsupportedMetric(
            f"no metric {name!r} in this run; it produced "
            f"{sorted(m.name for m in self.metrics)}"
        )

    def has(self, name: str) -> bool:
        return any(m.name == name for m in self.metrics)

    def as_payload(self) -> list[dict[str, Any]]:
        return [m.as_payload() for m in self.metrics]


@dataclass(frozen=True, slots=True)
class RunArtifact:
    """The complete, reproducible output of one execution.

    ``digest`` is over everything that identifies the computation *and* its
    result. Two runs of the same spec, seed and data must produce the same
    digest — that property is asserted by a test, because it is the whole
    basis on which a result can be cited.
    """

    spec_digest: str
    data_fingerprint: str
    code_version: str
    seed: int
    metrics: MetricSet
    series: dict[str, list[str]] = field(default_factory=dict)
    """Equity curve and exposures, as exact decimal strings."""

    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "spec_digest": self.spec_digest,
            "data_fingerprint": self.data_fingerprint,
            "code_version": self.code_version,
            "seed": self.seed,
            "metrics": self.metrics.as_payload(),
            "series": self.series,
            "diagnostics": self.diagnostics,
        }

    def digest(self) -> str:
        return sha256_of(self.as_payload())


@dataclass(frozen=True, slots=True)
class EngineCapabilities:
    """What this engine can and cannot do.

    Declared rather than discovered, so a spec can be refused *before* it
    runs and an agent gets told why.
    """

    name: str
    version: str
    available: bool
    detail: str
    signals: frozenset[str] = field(default_factory=frozenset)
    metrics: frozenset[str] = field(default_factory=frozenset)
    desks: frozenset[str] = field(default_factory=frozenset)
    deterministic: bool = True

    def supports(self, spec: ExperimentSpec) -> tuple[bool, str]:
        """Whether this engine can run ``spec``, and why not if it cannot."""
        if not self.available:
            return False, self.detail
        if spec.signal.kind not in self.signals:
            return False, (
                f"{self.name} does not implement signal {spec.signal.kind!r}; "
                f"it has {sorted(self.signals)}"
            )
        if spec.universe.desk not in self.desks:
            return False, (
                f"{self.name} does not cover the {spec.universe.desk} desk; "
                f"it covers {sorted(self.desks)}"
            )
        missing = sorted(set(spec.metrics) - self.metrics)
        if missing:
            return False, (
                f"{self.name} cannot compute {missing}; it produces "
                f"{sorted(self.metrics)}"
            )
        return True, ""


@runtime_checkable
class ResearchEngine(Protocol):
    """Anything that can turn a specification into measurements."""

    name: str

    def capabilities(self) -> EngineCapabilities: ...

    def run(self, spec: ExperimentSpec) -> RunArtifact: ...
