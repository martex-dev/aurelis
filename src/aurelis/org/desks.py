"""The seven market desks.

Desks are the second organizational dimension: they cross every department, and
an agent is ``(charter, desk)``. A Technical Analyst on the Options desk and
one on the FX desk share a remit and differ in tools, data, cost models and
playbooks.

This is what takes the company to hundreds of agents without a redesign — seven
desks times the charter roster, opened only where evidence justifies each hire.

Only CRYPTO is ``ACTIVE``. The rest are ``PROPOSED``: declared, so the roadmap
is legible and so nothing has to be invented later, but not open for business.
A desk opens when it has data, an engine, staff, a cost model and risk limits —
and **a desk without a realistic cost model cannot be opened at all**, because
a backtest without one is not evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = ["DESKS", "Desk", "DeskSpec", "DeskStatus", "active_desks"]


class Desk(StrEnum):
    CRYPTO = "crypto"
    EQUITIES = "equities"
    OPTIONS = "options"
    FUTURES = "futures"
    COMMODITIES = "commodities"
    FX = "fx"
    MEMECOIN = "memecoin"


class DeskStatus(StrEnum):
    PROPOSED = "proposed"
    """Declared but not open. No staff, no data, no research."""

    OPENING = "opening"
    ACTIVE = "active"

    DORMANT = "dormant"
    """Nothing studied here for the declared window. Costs nothing."""

    CLOSED = "closed"
    """Deliberately shut, with a recorded reason."""


@dataclass(frozen=True, slots=True)
class DeskSpec:
    desk: Desk
    name: str
    instruments: tuple[str, ...]
    engines: tuple[str, ...]
    data_sources: tuple[str, ...]
    calendar: str
    status: DeskStatus = DeskStatus.PROPOSED
    opens_at_milestone: str = ""
    """Which milestone brings this desk online. Stated so an empty desk reads
    as scheduled rather than forgotten."""

    notes: str = ""
    existing_tools: tuple[str, ...] = field(default_factory=tuple)
    """Tools that already exist elsewhere on disk and become this desk's
    capabilities. Recorded here so the audit's findings survive contact with
    the roadmap."""


DESKS: dict[Desk, DeskSpec] = {
    spec.desk: spec
    for spec in (
        DeskSpec(
            Desk.CRYPTO,
            "Crypto",
            ("spot", "perpetual", "funding", "basis"),
            ("martex",),
            ("ccxt_lake", "fixture"),
            calendar="24/7",
            status=DeskStatus.ACTIVE,
            opens_at_milestone="M1",
            notes="The engine and the validated data lake already exist.",
        ),
        DeskSpec(
            Desk.EQUITIES,
            "Equities",
            ("single_name", "etf", "index"),
            ("equities",),
            ("prices", "fundamentals", "filings", "factor_models"),
            calendar="XNYS",
            opens_at_milestone="M12",
            existing_tools=("factor-exposure",),
        ),
        DeskSpec(
            Desk.OPTIONS,
            "Options",
            ("listed_option", "vol_surface"),
            ("options",),
            ("chains", "implied_vol", "greeks", "term_structure"),
            calendar="XNYS",
            opens_at_milestone="M12",
            existing_tools=("vol-surface", "implied-move"),
        ),
        DeskSpec(
            Desk.FUTURES,
            "Futures",
            ("index_future", "rate_future", "term_structure"),
            ("futures",),
            ("continuous_contracts", "roll_calendars"),
            calendar="CME",
            opens_at_milestone="M12",
            existing_tools=("roll-yield",),
        ),
        DeskSpec(
            Desk.COMMODITIES,
            "Commodities",
            ("energy", "metals", "agriculture"),
            ("futures",),
            ("curves", "inventories", "seasonality"),
            calendar="CME",
            opens_at_milestone="M12",
            existing_tools=("roll-yield",),
        ),
        DeskSpec(
            Desk.FX,
            "FX",
            ("major", "cross", "carry"),
            ("fx",),
            ("bars", "rate_differentials", "central_bank_calendar"),
            calendar="24/5",
            opens_at_milestone="M12",
        ),
        DeskSpec(
            Desk.MEMECOIN,
            "Memecoins",
            ("micro_cap_token", "launch"),
            ("martex",),
            ("dexscreener", "geckoterminal", "wallet_cohorts"),
            calendar="24/7",
            opens_at_milestone="M12",
            notes="Highest data-quality risk of any desk; survivorship is the default state.",
        ),
    )
}


def active_desks() -> tuple[Desk, ...]:
    return tuple(d for d, spec in DESKS.items() if spec.status is DeskStatus.ACTIVE)
