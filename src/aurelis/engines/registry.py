"""Which engines exist, and which one can run a given specification.

The registry is what makes "an agent asks for something the engine cannot do"
a typed refusal naming the reason, rather than a plausible wrong number. It
also keeps the desk-to-engine mapping in one place, so opening a desk at M12
is registering a config rather than editing a dispatch chain.
"""

from __future__ import annotations

from aurelis.engines.local import LocalEngine
from aurelis.engines.martex import MartexEngine
from aurelis.engines.protocol import EngineCapabilities, ResearchEngine, UnsupportedMetric
from aurelis.engines.spec import ExperimentSpec

__all__ = ["available_engines", "engine_for", "engine_named", "survey"]

_ENGINES: dict[str, ResearchEngine] = {}


def _engines() -> dict[str, ResearchEngine]:
    if not _ENGINES:
        for engine in (LocalEngine(), MartexEngine()):
            _ENGINES[engine.name] = engine
    return _ENGINES


def engine_named(name: str) -> ResearchEngine:
    try:
        return _engines()[name]
    except KeyError:
        raise KeyError(
            f"no engine {name!r}; registered engines are {sorted(_engines())}"
        ) from None


def available_engines() -> tuple[str, ...]:
    """Engines that could actually run something right now."""
    return tuple(
        name for name, engine in sorted(_engines().items()) if engine.capabilities().available
    )


def engine_for(spec: ExperimentSpec) -> ResearchEngine:
    """The engine named by the spec, refusing with a reason if it cannot run it."""
    engine = engine_named(spec.engine)
    supported, reason = engine.capabilities().supports(spec)
    if not supported:
        raise UnsupportedMetric(reason)
    return engine


def survey() -> tuple[EngineCapabilities, ...]:
    """Every engine's declared state, for `aurelis doctor`."""
    return tuple(engine.capabilities() for _, engine in sorted(_engines().items()))
