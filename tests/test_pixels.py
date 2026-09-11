"""M37 — the facility in pixels.

The acceptance criteria, each with a test named after it:

* an avatar is deterministic, mirrored, distinct across agents, and escapes
  its title,
* a progress bar is the ratio with the numbers beside it, clamps, and draws
  nothing when there is nothing to measure,
* the facility is drawn crisp-edged; a room's LED blinks and its staff move
  only when the room is working,
* the mechanisms page shows a gathering mechanism as a bar of its record,
* an agent's page wears its avatar.

Nothing here touches the network.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aurelis.agents.tables import AgentState
from aurelis.org.departments import Department
from aurelis.runtime import Runtime
from aurelis.station import projections as proj
from aurelis.station.app import station_app
from aurelis.station.layout import build_facility
from aurelis.station.pixels import avatar_svg, progress_bar, sprite_rows
from aurelis.station.render import render_facility


@pytest.fixture
def company(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


def test_an_avatar_is_deterministic_mirrored_distinct_and_escaped() -> None:
    first = sprite_rows("AG-0001")
    assert first == sprite_rows("AG-0001")
    assert first != sprite_rows("AG-0002")
    assert len(first) == 8 and all(len(row) == 8 for row in first)
    assert all(row == row[::-1] for row in first), "a face reads because it is symmetric"
    assert first[3][3] and first[4][3], "every sprite has something in the middle"
    svg = avatar_svg("AG-0001", tone="var(--ok)", title="<script>")
    assert 'shape-rendering="crispEdges"' in svg and 'class="avatar"' in svg
    assert "<script>" not in svg and "&lt;script&gt;" in svg
    assert svg.count("<rect") == sum(sum(row) for row in first)


def test_a_progress_bar_is_the_ratio_with_the_numbers_beside_it() -> None:
    bar = progress_bar(7, 20)
    assert "width:35%" in bar and ">7/20<" in bar
    full = progress_bar(25, 20)
    assert "width:100%" in full and ">25/20<" in full, "clamped, and still honest"
    assert "width:0%" in progress_bar(-3, 20)
    assert progress_bar(1, 0) == "", "nothing to measure, nothing drawn"
    assert Decimal("0.35") == Decimal(7) / Decimal(20)


def test_the_facility_is_crisp_and_only_a_working_room_is_lit_and_moving(
    company: Runtime,
) -> None:
    facility = build_facility()
    with company.database.session() as session:
        statuses = proj.room_statuses(session)
    still = render_facility(facility, statuses).render()
    assert 'shape-rendering="crispEdges"' in still
    assert 'class="led on"' not in still and '<g class="busy">' not in still

    with company.database.session() as session:
        agent = company.roster.by_handle(session, "QUANT")
        company.roster.set_state(session, agent.ref, AgentState.WORKING)
        statuses = proj.room_statuses(session)
    assert statuses[Department.QUANTITATIVE_RESEARCH].busy
    lit = render_facility(facility, statuses).render()
    assert lit.count('class="led on"') == 1, "one room is working, one LED blinks"
    assert lit.count('<g class="busy">') == 1, "and only its staff move"
    assert lit.count('class="led"') == still.count('class="led"') - 1


def test_the_mechanisms_page_shows_a_gathering_mechanism_as_a_bar_of_its_record(
    company: Runtime,
) -> None:
    from aurelis.mechanism.library import MIN_SCORED_PREDICTIONS

    with company.database.session() as session:
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="a bar to fill",
            trigger_kind="price.range_break",
            desk="crypto",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.6"),
            why="stops above the range are run and the forced buying carries the close.",
            other_side="the shorts whose stops sit just above the range.",
            decay="it fades as the stops move, within months.",
            origin="invented",
            found_on_instrument="BTC-USD",
            found_on_event="test",
            model="test",
        )
    page = station_app(company).handle("/mechanisms", {}).body.decode()
    assert f">0/{MIN_SCORED_PREDICTIONS}<" in page and "width:0%" in page
    detail = station_app(company).handle(f"/mechanism/{mechanism.ref}", {}).body.decode()
    assert f">0/{MIN_SCORED_PREDICTIONS}<" in detail
    assert 'class="avatar"' in detail, "the author's portrait is on the statement"


def test_an_agents_page_wears_its_avatar(company: Runtime) -> None:
    with company.database.session() as session:
        ref = company.roster.by_handle(session, "QUANT").ref
    page = station_app(company).handle(f"/agent/{ref}", {}).body.decode()
    assert 'class="avatar"' in page and f'aria-label="{ref} QUANT"' in page
    assert page.count("<h1>") == 1 and page.index('class="avatar"') > page.index("<h1>")
