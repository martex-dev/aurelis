"""Filling the building: the generalists split into specialists (M66).

The launch roster staffed each department with one generalist covering every
charter in it. INTEL held nine market-intelligence charters at once: head,
fundamental, news, sentiment, technical, macro, regime, alternative data
and source reliability. QUANT held seven. So seven agents formed views,
and each was "basic at everything". That is the operator's exact complaint:
"AI have a huge knowledge but don't specialize". The building had fifty rooms'
worth of charters and seven people in it.

This module splits those charters onto specialists through the company's own
fission (``orgdev/handover.py``). The charter moves with its coverage, its
tasks and its channel memberships. Each specialist then goes through the M10
onboarding gate like any hire, and works from its own charter. ``identity_of``
puts each charter's remit in front of the agent at every seat, so a News
Analyst reads the material as a news analyst and a Technical Analyst as a
technical analyst, and their methods (M48) evolve apart from there.

More agents is not assumed to be better (CLAUDE.md §16). Every specialist has
its own forward record from its first view, and the evolution and calibration
machinery already says, per agent, who beats a coin and who does not.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

__all__ = ["SPECIALISTS", "Specialist", "fill_the_building"]


@dataclass(frozen=True, slots=True)
class Specialist:
    handle: str
    from_handle: str
    charters: tuple[str, ...]


SPECIALISTS: tuple[Specialist, ...] = (
    # Market Intelligence: INTEL keeps the head, regime and source reliability.
    Specialist("NEWS", "INTEL", ("intel.news_analyst",)),
    Specialist("SOCIAL", "INTEL", ("intel.sentiment_analyst",)),
    Specialist("TECH", "INTEL", ("intel.technical_analyst",)),
    Specialist("MACRO", "INTEL", ("intel.macro_analyst",)),
    Specialist("ONCHAIN", "INTEL", ("intel.alternative_data_analyst",)),
    Specialist("FUND", "INTEL", ("intel.fundamental_analyst",)),
    # Quant Research: QUANT keeps the quant, data, factor and simulation charters.
    Specialist("STAT", "QUANT", ("research.statistical",)),
    Specialist("BACKTEST", "QUANT", ("research.backtest",)),
    Specialist("ML", "QUANT", ("research.ml",)),
    # Strategy Lab.
    Specialist("ARCH", "STRAT", ("strategy.architect",)),
    Specialist("ROBUST", "VALID", ("strategy.robustness",)),
    Specialist("ADV", "CRITIC", ("strategy.adversarial",)),
)
"""Twelve specialists. With the seven who already formed views, nineteen agents
form views, the "twenty AIs, each good at a different thing" the operator
described."""


def fill_the_building(runtime: Any, *, at: dt.datetime | None = None) -> list[str]:
    """Split every specialist that does not exist yet, then onboard them.

    Idempotent: a specialist already hired is skipped, and so is one whose
    generalist no longer holds the charter (it was split some other way).
    Returns the handles hired.
    """
    from aurelis.agents.tables import Agent
    from aurelis.org.charters import Seniority

    moment = at or runtime.clock.now()
    hired: list[str] = []
    with runtime.database.session() as session:
        existing = set(session.execute(sa.select(Agent.handle)).scalars())
        for spec in SPECIALISTS:
            if spec.handle in existing:
                continue
            try:
                source = runtime.roster.by_handle(session, spec.from_handle)
            except KeyError:
                continue
            held = set(runtime.roster.coverage_of(session, source.ref))
            if not set(spec.charters) <= held or not (held - set(spec.charters)):
                continue
            runtime.handover.split(
                session,
                from_ref=source.ref,
                handle=spec.handle,
                charters=spec.charters,
                seniority=Seniority.SENIOR,
                change_ref="M66",
                note=f"specialist split from {spec.from_handle} (M66)",
                at=moment,
            )
            hired.append(spec.handle)
        if hired:
            runtime.roster.onboard_all(session, at=moment, onboarding=runtime.onboarding)
    return hired
