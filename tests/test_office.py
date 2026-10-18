"""M61 — the Office: the company drawn as the building it works in.

The acceptance criteria, each with a test named after it:

* every department has a room, the Control Room is the biggest and sits in the
  middle, and no two rooms overlap,
* every hallway and lift in the plan is drawn, and cuts a doorway at both ends,
* every agent on the payroll is drawn in the room it works in, and nobody else
  is; the Company Manager is in the Control Room,
* a figure moves only while the record says it is working,
* the Office is the station's front door and the old facility is still there,
* every room opens a dashboard of tabs, the heavy ones built when opened,
* the Control Room says whether the company is thinking and how far it is
  from asking for real money.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import EventKind
from aurelis.office.art import _shell, plan
from aurelis.office.live import MANAGER_HANDLE, SERVICE_REF, live_state, people, room_panel
from aurelis.office.map import CONTROL, LINKS, ROOMS
from aurelis.org.departments import DEPARTMENTS
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.station.app import station_app

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


def _act(company: Runtime, handle: str, *, minutes_ago: float) -> str:
    with company.database.session() as session:
        ref = str(company.roster.by_handle(session, handle).ref)
        company.ledger.append(
            session,
            kind=EventKind.MODEL_CALLED,
            actor=ref,
            subject=None,
            payload={"model": "m"},
            at=_NOW - dt.timedelta(minutes=minutes_ago),
        )
    return ref


# ------------------------------------------------------------ the plan


def test_every_department_has_a_room_and_the_control_room_is_the_heart() -> None:
    departments = {room.department for room in ROOMS if room.department is not None}
    assert departments == set(DEPARTMENTS)
    shells = {room.room_id: _shell(room) for room in ROOMS}
    control = shells[CONTROL]
    assert all(
        control.w * control.h > box.w * box.h for rid, box in shells.items() if rid != CONTROL
    )
    xs = [box.x + box.w / 2 for box in shells.values()]
    ys = [box.y + box.h / 2 for box in shells.values()]
    middle = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    assert control.x < middle[0] < control.x + control.w
    assert control.y < middle[1] < control.y + control.h
    boxes = list(shells.items())
    for i, (one, a) in enumerate(boxes):
        for two, b in boxes[i + 1 :]:
            assert not a.intersects(b), f"{one} overlaps {two}"


def test_every_hallway_and_lift_is_drawn_and_cuts_a_doorway_at_both_ends() -> None:
    layout = plan([])
    assert len(layout["halls"]) == len(LINKS)
    for first, second in LINKS:
        assert layout["doorways"][first], first
        assert layout["doorways"][second], second
    for hall in layout["halls"]:
        assert hall["w"] > 0 and hall["h"] > 0


# ------------------------------------------------------------ the people


def test_every_agent_on_the_payroll_is_drawn_where_it_works(company: Runtime) -> None:
    with company.database.session() as session:
        everyone = people(session)
    refs = {person.ref for person in everyone}
    with company.database.session() as session:
        from aurelis.agents.tables import Agent

        payroll = {
            str(a.ref): (str(a.handle), str(a.department))
            for a in session.query(Agent).filter(Agent.retired_at.is_(None))
        }
    assert refs == set(payroll) | {SERVICE_REF}
    for person in everyone:
        if person.ref == SERVICE_REF:
            assert person.room_id == "infrastructure"
            continue
        handle, department = payroll[person.ref]
        if handle == MANAGER_HANDLE:
            assert person.room_id == CONTROL
        else:
            assert person.room_id == department
    layout = plan(everyone)
    drawn = [s["ref"] for sprites in layout["sprites"].values() for s in sprites]
    assert sorted(drawn) == sorted(refs), "one figure per person, and nobody else"


def test_a_figure_moves_only_while_the_record_says_it_is_working(company: Runtime) -> None:
    busy = _act(company, "QUANT", minutes_ago=3)
    idle = _act(company, "INTEL", minutes_ago=90)
    with company.database.session() as session:
        state = live_state(session, _NOW)
    assert state["agents"][busy]["working"] is True
    assert state["agents"][idle]["working"] is False
    assert state["rooms"]["quantitative_research"]["working"] >= 1
    page = station_app(company).handle("/", {}).body.decode()
    assert ".agent:not(.working) .pace" in page, "an idle figure stands at its post"
    assert f'data-agent="{busy}"' in page and f'data-agent="{idle}"' in page


# ------------------------------------------------------------ the pages


def test_the_office_is_the_front_door_and_the_facility_is_still_there(company: Runtime) -> None:
    app = station_app(company)
    office = app.handle("/", {}).body.decode()
    assert "Aurelis &mdash; the Office" in office
    for room in ROOMS:
        assert f'data-room="{room.room_id}"' in office
    facility = app.handle("/facility", {}).body.decode()
    assert "Who is doing what" in facility
    live = json.loads(app.handle("/office/live.json", {}).body)
    assert {"health", "agents", "rooms", "feed", "wake"} <= set(live)


def test_every_room_opens_a_dashboard_and_the_heavy_tabs_open_when_asked(
    company: Runtime,
) -> None:
    app = station_app(company)
    for room in ROOMS:
        response = app.handle(f"/office/room/{room.room_id}", {})
        assert response.status == 200, room.room_id
        body = response.body.decode()
        assert "class='tabbtn on'" in body and "<section data-tab=" in body
        if room.room_id != CONTROL:
            assert "what happens here" in body
            assert "data-src='/office/tab/" in body, "the heavy tab is lazy"
    tab = app.handle("/office/tab/mechanisms", {})
    assert tab.status == 200
    assert app.handle("/office/tab/nonsense", {}).status == 404
    assert app.handle("/office/room/nowhere", {}).status == 404


def test_the_control_room_says_whether_the_company_is_thinking_and_how_far_from_money(
    company: Runtime,
) -> None:
    _act(company, "QUANT", minutes_ago=2)
    with company.database.session() as session:
        body = room_panel(session, CONTROL, _NOW)
    assert body is not None
    assert "class='health thinking'" in body
    assert "ready for real money?" in body
    assert "working now" in body
    for room in ROOMS:
        if room.room_id != CONTROL:
            assert f"data-room='{room.room_id}'" in body, "every room is one click away"


def test_an_agent_opens_its_profile_over_the_map(company: Runtime) -> None:
    ref = _act(company, "CRITIC", minutes_ago=1)
    response = station_app(company).handle(f"/office/agent/{ref}", {})
    assert response.status == 200 and ref in response.body.decode()
    assert station_app(company).handle("/office/agent/AG-9999", {}).status == 404
