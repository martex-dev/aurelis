"""What must be true before a desk may open, checked rather than asserted.

`docs/02-organization.md` says a desk opens when it has data, an engine, staff,
a cost model and risk limits — and that **a desk without a realistic cost model
cannot be opened at all**. This module turns that sentence into a checklist
that is actually evaluated, item by item, against the running system.

Every check returns one of three things, and the third is the point:

``PASS``      the requirement is met, and the detail says how
``FAIL``      it is not met, and the detail says what is missing
``PROVISIONAL``  it is met by something honest but temporary

``PROVISIONAL`` is what stops this from being a rubber stamp. Every desk M12
opens runs on **fixture data with no live feed behind it**. That is a real
limitation and it must not be able to read as a pass — but it also must not
block the desk, because the whole point of opening on fixtures is to exercise
the machinery before there is a feed to break. So it gets its own state, it is
carried on the opening record, and every report of a provisionally open desk
repeats it.

A desk may open with provisional items. A desk may **not** open with a failure,
and the check that most often fails is the cost model: a desk whose round-trip
cost is zero cannot be opened, because a backtest without costs is not
evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from aurelis.desks.calendars import CALENDARS, calendar_for
from aurelis.desks.costs import costs_for
from aurelis.org.desks import DESKS, Desk

__all__ = ["CHECKS", "Readiness", "ReadinessCheck", "ReadinessItem", "assess"]


class Readiness(StrEnum):
    PASS = "pass"
    PROVISIONAL = "provisional"
    """Met by something honest and temporary. Never silently a pass."""

    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ReadinessItem:
    """One requirement, and what the system actually said about it."""

    name: str
    state: Readiness
    detail: str

    def as_payload(self) -> dict[str, Any]:
        return {"name": self.name, "state": self.state.value, "detail": self.detail}

    def describe(self) -> str:
        return f"{self.state.value.upper():<12} {self.name}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    """One requirement, and how to find out."""

    name: str
    asks: str
    run: Callable[[Desk], ReadinessItem]


def _registered(desk: Desk) -> ReadinessItem:
    spec = DESKS.get(desk)
    if spec is None:  # pragma: no cover - Desk is a closed enum
        return ReadinessItem("registered", Readiness.FAIL, "no DeskSpec")
    return ReadinessItem(
        "registered",
        Readiness.PASS,
        f"{spec.name}: {len(spec.instruments)} instrument kinds, "
        f"engines {list(spec.engines)}",
    )


def _calendar(desk: Desk) -> ReadinessItem:
    spec = DESKS[desk]
    if spec.calendar not in CALENDARS:
        return ReadinessItem(
            "calendar",
            Readiness.FAIL,
            f"the registry names calendar {spec.calendar!r}, which is not "
            f"declared. Without it no metric on this desk can be annualised, "
            "so nothing it produces is comparable with any other desk.",
        )
    cal = calendar_for(desk.value)
    return ReadinessItem(
        "calendar",
        Readiness.PASS,
        f"{cal.describe()}; {cal.periods_per_year('1h')} hourly bars a year",
    )


def _cost_model(desk: Desk) -> ReadinessItem:
    try:
        model = costs_for(desk)
    except KeyError as exc:
        return ReadinessItem("cost model", Readiness.FAIL, str(exc))
    if model.round_trip_bps <= Decimal(0):
        return ReadinessItem(
            "cost model",
            Readiness.FAIL,
            "round-trip cost is zero. A backtest without costs is not "
            "evidence, and this desk may not be opened.",
        )
    if not model.basis.strip():
        return ReadinessItem(
            "cost model",
            Readiness.FAIL,
            "the cost model states no basis. A number with no stated source is "
            "a number somebody typed.",
        )
    return ReadinessItem("cost model", Readiness.PASS, model.describe())


def _liquidity(desk: Desk) -> ReadinessItem:
    model = costs_for(desk)
    liquidity = model.liquidity
    if liquidity.material_size_usd <= Decimal(0):
        return ReadinessItem(
            "liquidity",
            Readiness.FAIL,
            "no material size declared, so no backtest on this desk could be "
            "told it had traded more than the market would bear",
        )
    short = "shortable" if liquidity.shortable else "long only"
    return ReadinessItem(
        "liquidity",
        Readiness.PASS,
        f"material size ${liquidity.material_size_usd}, {short}, "
        f"T+{liquidity.settlement_days}",
    )


def _data(desk: Desk) -> ReadinessItem:
    from aurelis.desks.sources import DESK_FIXTURES

    spec = DESKS[desk]
    if desk is Desk.CRYPTO:
        return ReadinessItem(
            "data",
            Readiness.PROVISIONAL,
            "fixture bars from M1 plus the validated martex lake behind the "
            "adapter. No live exchange feed is wired in this repository.",
        )
    if desk not in DESK_FIXTURES:
        return ReadinessItem(
            "data", Readiness.FAIL, "no source of any kind for this desk"
        )
    fixture = DESK_FIXTURES[desk]
    return ReadinessItem(
        "data",
        Readiness.PROVISIONAL,
        f"{fixture.name}: {len(fixture.symbols())} live names, "
        f"{len(fixture.universe.casualties)} delisted. Deterministic, offline, "
        f"and not a market. The declared feed ({spec.data_sources[0]}) is not "
        "wired, so nothing on this desk is a claim about a real one.",
    )


def _prices_move(desk: Desk) -> ReadinessItem:
    """Whether the desk's data actually varies.

    Added because two desks shipped with completely flat series and nothing
    caught it: the engine ran, the metrics computed, the verdict rule returned
    UNDERPOWERED, and no part of the system said the input had been a constant.
    A desk whose prices cannot move cannot produce evidence, and that is a
    failure rather than a caveat.
    """
    from aurelis.desks.sources import DESK_FIXTURES

    if desk not in DESK_FIXTURES:
        return ReadinessItem(
            "prices move",
            Readiness.PASS,
            "crypto reads the M1 fixture, whose movement is asserted there",
        )
    fixture = DESK_FIXTURES[desk]
    flat = [s for s in fixture.symbols() if not fixture.moves(s)]
    if flat:
        return ReadinessItem(
            "prices move",
            Readiness.FAIL,
            f"{', '.join(flat)} produce a constant series at tick "
            f"{fixture.tick}. A desk whose prices cannot move cannot produce "
            "evidence, and every metric computed on one is a measurement of "
            "the rounding.",
        )
    return ReadinessItem(
        "prices move",
        Readiness.PASS,
        f"all {len(fixture.symbols())} names vary at tick {fixture.tick}",
    )


def _engine(desk: Desk) -> ReadinessItem:
    from aurelis.engines.registry import engine_named

    spec = DESKS[desk]
    covered = []
    for name in ("local", *spec.engines):
        try:
            engine = engine_named(name)
        except KeyError:
            continue
        caps = engine.capabilities()
        if desk.value in caps.desks and caps.available:
            covered.append(name)
    if not covered:
        return ReadinessItem(
            "engine",
            Readiness.FAIL,
            f"no available engine covers the {desk.value} desk; it names "
            f"{list(spec.engines)}",
        )
    return ReadinessItem(
        "engine", Readiness.PASS, f"covered by {', '.join(sorted(set(covered)))}"
    )


def _limits(desk: Desk) -> ReadinessItem:
    from aurelis.desks.limits import limits_for

    limits = limits_for(desk)
    return ReadinessItem("risk limits", Readiness.PASS, limits.describe())


def _scenarios(desk: Desk) -> ReadinessItem:
    """Whether the training suite has questions for this desk.

    It does not. The M10 catalogue is twelve crypto-shaped worlds, and a desk
    opened without its own planted defects has not been shown to be researchable
    — only to be runnable. Naming that as provisional is the honest reading, and
    it is the first item on the M13 list.
    """
    return ReadinessItem(
        "scenario suite",
        Readiness.PROVISIONAL,
        "the M10 catalogue plants defects in crypto-shaped worlds only. No "
        "desk-specific scenarios exist, so agents on this desk are scored on "
        "another desk's questions.",
    )


CHECKS: tuple[ReadinessCheck, ...] = (
    ReadinessCheck("registered", "Is there a DeskSpec?", _registered),
    ReadinessCheck("calendar", "Can its research be annualised?", _calendar),
    ReadinessCheck("cost model", "Would a backtest here be evidence?", _cost_model),
    ReadinessCheck("liquidity", "Is there a cap on what it may claim to trade?", _liquidity),
    ReadinessCheck("data", "Is there anything to measure?", _data),
    ReadinessCheck("prices move", "Does that anything actually vary?", _prices_move),
    ReadinessCheck("engine", "Can anything compute a result?", _engine),
    ReadinessCheck("risk limits", "What bounds it?", _limits),
    ReadinessCheck("scenario suite", "Can agents here be scored?", _scenarios),
)
"""The nine things a desk needs. Evaluated in order, and all of them run —
a checklist that stopped at the first failure would report one problem at a
time and make opening a desk an iterative guessing game."""


@dataclass(frozen=True, slots=True)
class Assessment:
    """Every check, and whether the desk may open."""

    desk: Desk
    items: tuple[ReadinessItem, ...]

    @property
    def failures(self) -> tuple[ReadinessItem, ...]:
        return tuple(i for i in self.items if i.state is Readiness.FAIL)

    @property
    def provisional(self) -> tuple[ReadinessItem, ...]:
        return tuple(i for i in self.items if i.state is Readiness.PROVISIONAL)

    @property
    def may_open(self) -> bool:
        """A failure blocks; a provisional item does not, and is carried."""
        return not self.failures

    @property
    def caveats(self) -> tuple[str, ...]:
        return tuple(f"{i.name}: {i.detail}" for i in self.provisional)

    def as_payload(self) -> dict[str, Any]:
        return {
            "desk": self.desk.value,
            "items": [i.as_payload() for i in self.items],
            "may_open": self.may_open,
            "caveats": list(self.caveats),
        }

    def describe(self) -> str:
        if self.failures:
            return (
                f"{self.desk.value}: BLOCKED — "
                + "; ".join(i.name for i in self.failures)
            )
        return (
            f"{self.desk.value}: may open with {len(self.provisional)} "
            "provisional item(s)"
        )


def assess(desk: Desk | str) -> Assessment:
    """Run every check against the live system."""
    key = Desk(desk) if isinstance(desk, str) else desk
    return Assessment(desk=key, items=tuple(check.run(key) for check in CHECKS))
