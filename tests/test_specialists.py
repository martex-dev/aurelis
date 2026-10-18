"""M66 — filling the building: the generalists split into specialists.

The acceptance criteria, each with a test named after it:

* twelve specialists are split off the generalists through the company's own
  fission, each passing the onboarding gate before it works,
* the generalists keep the charters not split, and nobody is left empty,
* doing it twice hires nobody twice,
* every specialist reads the material through its own charter's remit,
* nineteen agents now form views, and the Office draws every one of them.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.agents.tables import Agent
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.orgdev.specialists import SPECIALISTS, fill_the_building
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime

_NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def company(settings: Settings) -> Any:
    built = Runtime.build(
        settings, clock=FrozenClock(_NOW), provider=MockProvider(responder=standins())
    )
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def test_twelve_specialists_are_split_off_and_onboarded(company: Runtime) -> None:
    hired = fill_the_building(company)
    assert sorted(hired) == sorted(s.handle for s in SPECIALISTS)
    with company.database.session() as session:
        states = dict(
            session.execute(
                sa.select(Agent.handle, Agent.state).where(Agent.handle.in_(hired))
            ).all()
        )
        fissions = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = 'org.fission'")
        ).scalar_one()
        news = company.roster.by_handle(session, "NEWS")
        intel = company.roster.by_handle(session, "INTEL")
        news_holds = company.roster.coverage_of(session, news.ref)
        intel_holds = set(company.roster.coverage_of(session, intel.ref))
    assert set(states.values()) == {"active"}, states
    assert fissions == len(SPECIALISTS)
    assert news_holds == ("intel.news_analyst",)
    assert "intel.news_analyst" not in intel_holds and "intel.head" in intel_holds


def test_doing_it_twice_hires_nobody_twice(company: Runtime) -> None:
    fill_the_building(company)
    assert fill_the_building(company) == []


def test_every_specialist_reads_the_material_through_its_own_remit(company: Runtime) -> None:
    from aurelis.judgement.seat import identity_of

    fill_the_building(company)
    with company.database.session() as session:
        news = identity_of(company.roster.by_handle(session, "NEWS"), session)
        tech = identity_of(company.roster.by_handle(session, "TECH"), session)
    assert "News Analyst (Event detection, materiality" in news
    assert "Technical Analyst (Price structure, trend" in tech
    assert "News Analyst" not in tech


def test_nineteen_agents_form_views_and_the_office_draws_them(company: Runtime) -> None:
    from aurelis.autonomy.agenda import _judges
    from aurelis.office.art import plan
    from aurelis.office.live import people

    fill_the_building(company)
    with company.database.session() as session:
        judges = {a.handle for a in _judges(session)}
        everyone = people(session)
    assert len(judges) == 19, sorted(judges)
    assert {s.handle for s in SPECIALISTS} <= judges
    layout = plan(everyone)
    drawn = {s["label"] for sprites in layout["sprites"].values() for s in sprites}
    assert {s.handle for s in SPECIALISTS} <= drawn
    builds = {s["label"]: s["role"] for sprites in layout["sprites"].values() for s in sprites}
    assert builds["ADV"] == "skeptic" and builds["NEWS"] == "literature"
