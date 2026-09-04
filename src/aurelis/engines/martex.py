"""The martex-quant adapter.

martex-quant is a tool in the toolbox, not the system (ADR-0001). This is the
only place Aurelis touches it, and the boundary has a shape worth stating
because it is not the obvious one.

**Its statistics are pure functions and are called in-process.**
``probabilistic_sharpe_ratio``, ``expected_max_sharpe`` and the bootstrap
routines take numbers and return numbers. They touch no filesystem and no
network, so subprocessing them would buy nothing and cost a process spawn per
metric.

**Its data and backtest paths are not, and must be subprocessed.** martex-quant
resolves almost every path relative to the working directory and ``chdir``s
into a *workspace* before dispatching — a deliberate design of its own, and a
correct one for a CLI. Called in-process it would silently move Aurelis's
working directory, so anything that reaches the data lake runs in a child
process with an explicit ``MARTEX_QUANT_HOME``.

What the adapter is actually for
--------------------------------

The deflated Sharpe ratio. It is the mechanism that makes a research corpus
honest at scale: the bar for any claim rises with **every trial the company has
ever run**, so a finding drawn from a thousand quiet attempts has to clear a
higher hurdle than one drawn from three. Aurelis could reimplement it; wrapping
the version that has already been used across a real 174-trial corpus is better,
and it is exactly the kind of thing ADR-0001 says to call rather than fork.

When martex-quant is not installed, the adapter reports that and refuses. It
never falls back to an approximation of its own, because a metric that
sometimes means one thing and sometimes another is worse than a missing one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from aurelis.engines.protocol import (
    EngineCapabilities,
    EngineUnavailable,
    Metric,
    MetricSet,
    RunArtifact,
    UnsupportedMetric,
)
from aurelis.engines.spec import ExperimentSpec

__all__ = ["MartexEngine", "MartexStatistics", "deflated_sharpe", "martex_version"]

_HOME_ENV = "MARTEX_QUANT_HOME"
_SUBPROCESS_TIMEOUT = 600


def martex_version() -> str | None:
    """The installed version, or ``None`` if it is not importable."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("martex-quant")
    except (ImportError, PackageNotFoundError):
        return None


@dataclass(frozen=True, slots=True)
class DeflatedSharpe:
    """A Sharpe ratio, deflated for how many attempts produced it."""

    observed: Decimal
    deflated: Decimal
    benchmark: Decimal
    n_trials: int
    n_observations: int

    @property
    def clears_the_bar(self) -> bool:
        """The conventional threshold: a deflated ratio above 0.95."""
        return self.deflated > Decimal("0.95")


def deflated_sharpe(
    *,
    observed_sharpe: float,
    n_observations: int,
    n_trials: int,
    trial_sharpe_variance: float,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> DeflatedSharpe:
    """Probability that an observed Sharpe survives the trials that produced it.

    Calls martex-quant's own implementation rather than reimplementing it. The
    two pieces:

    * ``expected_max_sharpe(n_trials, variance)`` — the highest Sharpe you would
      expect from that many attempts *by chance alone*. This is the number that
      makes the graveyard load-bearing: every failed trial raises it.
    * ``probabilistic_sharpe_ratio(...)`` against that benchmark — the
      probability the true Sharpe exceeds what luck would have handed you.

    Raises :class:`EngineUnavailable` when martex-quant is absent. It does not
    approximate, because a metric that sometimes means one thing and sometimes
    another is worse than a missing one.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be at least 1; the trial itself counts")
    try:
        from martex_quant.backtesting.metrics import (
            expected_max_sharpe,
            probabilistic_sharpe_ratio,
        )
    except ImportError as error:  # pragma: no cover - exercised by availability
        raise EngineUnavailable(
            "martex-quant is not installed, so the deflated Sharpe ratio cannot "
            "be computed. Install it (pip install 'aurelis[engines]') or use a "
            "metric this workspace can actually produce."
        ) from error

    benchmark = (
        expected_max_sharpe(n_trials, trial_sharpe_variance) if n_trials > 1 else 0.0
    )
    value = probabilistic_sharpe_ratio(
        sharpe=observed_sharpe,
        n_obs=n_observations,
        skew=skew,
        kurtosis=kurtosis,
        benchmark_sharpe=benchmark,
    )
    return DeflatedSharpe(
        observed=Decimal(str(round(observed_sharpe, 8))),
        deflated=Decimal(str(round(value, 8))),
        benchmark=Decimal(str(round(benchmark, 8))),
        n_trials=n_trials,
        n_observations=n_observations,
    )


class MartexStatistics:
    """The pure-function half of the adapter. Safe in-process."""

    name = "martex.stats"

    @staticmethod
    def available() -> tuple[bool, str]:
        version = martex_version()
        if version is None:
            return False, "martex-quant is not installed (pip install 'aurelis[engines]')"
        return True, f"martex-quant {version}; pure statistics called in-process"

    @staticmethod
    def deflate(
        sharpe: Decimal,
        *,
        n_observations: int,
        n_trials: int,
        trial_sharpe_variance: float = 0.25,
    ) -> Metric:
        """A ``deflated_sharpe`` metric, ready to attach to a run."""
        result = deflated_sharpe(
            observed_sharpe=float(sharpe),
            n_observations=n_observations,
            n_trials=n_trials,
            trial_sharpe_variance=trial_sharpe_variance,
        )
        return Metric(
            name="deflated_sharpe",
            value=result.deflated,
            unit="probability",
            method=(
                f"martex.probabilistic_sharpe_ratio@{martex_version()} "
                f"vs expected_max_sharpe(n_trials={n_trials})"
            ),
        )


class MartexEngine:
    """Backtests and data, through martex-quant's CLI in a child process.

    Not used by CI, and honest about why: martex-quant's backtest path needs a
    workspace with a populated Parquet data lake, and that lake is built by
    pulling real market history over the network. A test that needed it would
    depend on what the market did that morning.
    """

    name = "martex"

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace

    # --------------------------------------------------------- availability

    def capabilities(self) -> EngineCapabilities:
        version = martex_version()
        if version is None:
            return EngineCapabilities(
                name=self.name,
                version="",
                available=False,
                detail="martex-quant is not installed (pip install 'aurelis[engines]')",
            )
        workspace = self._resolve_workspace()
        if workspace is None:
            return EngineCapabilities(
                name=self.name,
                version=version,
                available=False,
                detail=(
                    f"martex-quant {version} is installed but no workspace was found. "
                    f"Set {_HOME_ENV} to a directory initialised with "
                    "`martex-quant init`, holding a populated data lake."
                ),
            )
        return EngineCapabilities(
            name=self.name,
            version=version,
            available=True,
            detail=f"martex-quant {version} at {workspace}",
            signals=frozenset({"momentum", "mean_reversion", "rotation", "breakout"}),
            metrics=frozenset(
                {"total_return", "sharpe", "max_drawdown", "n_trades", "deflated_sharpe"}
            ),
            desks=frozenset({"crypto"}),
            deterministic=True,
        )

    def _resolve_workspace(self) -> Path | None:
        if self._workspace is not None:
            return self._workspace if (self._workspace / "data").is_dir() else None
        from_env = os.environ.get(_HOME_ENV)
        if not from_env:
            return None
        candidate = Path(from_env).expanduser()
        return candidate if (candidate / "data").is_dir() else None

    # ------------------------------------------------------------------ run

    def run(self, spec: ExperimentSpec) -> RunArtifact:
        capabilities = self.capabilities()
        supported, reason = capabilities.supports(spec)
        if not supported:
            raise UnsupportedMetric(reason) if capabilities.available else EngineUnavailable(
                reason
            )

        workspace = self._resolve_workspace()
        assert workspace is not None  # guaranteed by capabilities.available
        payload = self._invoke(workspace, spec)
        return self._to_artifact(spec, payload)

    def _invoke(self, workspace: Path, spec: ExperimentSpec) -> dict[str, Any]:
        """Run martex-quant in a child process with an explicit workspace.

        Never in-process: martex-quant ``chdir``s into its workspace, and doing
        that inside Aurelis would leave every later relative path in this
        process pointing somewhere nobody chose.
        """
        command = [
            sys.executable,
            "-m",
            "martex_quant.cli",
            "--workspace",
            str(workspace),
            "backtest",
            "--symbol",
            spec.universe.symbols[0],
            "--json",
        ]
        environment = {**os.environ, _HOME_ENV: str(workspace)}
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                command,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
                env=environment,
                check=False,
                cwd=str(workspace),
            )
        except subprocess.TimeoutExpired as error:
            raise EngineUnavailable(
                f"martex-quant did not finish within {_SUBPROCESS_TIMEOUT}s"
            ) from error

        if completed.returncode != 0:
            raise EngineUnavailable(
                f"martex-quant exited {completed.returncode}: "
                f"{completed.stderr.strip()[:400]}"
            )
        try:
            parsed: dict[str, Any] = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise EngineUnavailable(
                "martex-quant produced output this adapter could not parse; the "
                "contract between them has drifted and must be repaired rather "
                "than guessed at"
            ) from error
        return parsed

    def _to_artifact(self, spec: ExperimentSpec, payload: dict[str, Any]) -> RunArtifact:
        metrics = tuple(
            Metric(
                name=name,
                value=Decimal(str(value)),
                method=f"martex@{martex_version()}",
            )
            for name, value in payload.get("metrics", {}).items()
            if name in spec.metrics
        )
        return RunArtifact(
            spec_digest=spec.digest(),
            data_fingerprint=str(payload.get("data_fingerprint", "")),
            code_version=f"martex-quant@{martex_version()}",
            seed=spec.seed,
            metrics=MetricSet(metrics),
            diagnostics={"engine": "martex", "raw_keys": sorted(payload)},
        )
