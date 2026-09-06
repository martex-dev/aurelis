"""M7: Mission Control.

The acceptance criterion is a sentence about a person: *run a full mission and
understand what happened, who did it, what it cost, what was decided, who
disagreed and what failed — without opening a terminal, a source file or a raw
log.* :func:`test_the_whole_review_is_legible_without_a_terminal` is that
sentence turned into assertions.

Everything else here defends the two rules the station rests on: that a number
cannot reach a page without naming its source, and that the drawing shows the
record rather than a design — including the rooms that are empty.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from aurelis.agents.tables import AgentState
from aurelis.org.departments import DEPARTMENTS, Department
from aurelis.org.desks import DESKS
from aurelis.research.review import hold_research_review
from aurelis.runtime import Runtime
from aurelis.station import projections as proj
from aurelis.station.app import StationApp, serve, station_app
from aurelis.station.build import build_sealed
from aurelis.station.figures import Figure, Source, SourceKind
from aurelis.station.layout import COLUMNS, RoomKind, build_facility
from aurelis.station.render import render_facility
from aurelis.station.svg import Anchor, Label, collisions


@pytest.fixture
def company(runtime: Runtime) -> Runtime:
    runtime.staff()
    return runtime


@pytest.fixture
def reviewed(company: Runtime) -> Runtime:
    """A company that has run the M5 review end to end.

    The station's job is to make that story readable, so the fixture produces
    the story rather than hand-built rows.
    """
    with company.database.session() as session:
        refs = {
            handle: company.roster.by_handle(session, handle).ref
            for handle in ("QUANT", "CRITIC", "OPS", "GOV", "LEAD-R")
        }
        hold_research_review(
            session,
            research=company.research,
            chair=company.chair,
            author=refs["QUANT"],
            critic=refs["CRITIC"],
            chair_ref=refs["OPS"],
            participants=(refs["QUANT"], refs["CRITIC"], refs["LEAD-R"]),
            registrar=refs["GOV"],
        )
    return company


def _app(runtime: Runtime) -> StationApp:
    return station_app(runtime)


def _get(app: StationApp, path: str) -> str:
    response = app.handle(path, {})
    assert response.status == 200, f"{path} returned {response.status}"
    return response.body.decode("utf-8")


# ----------------------------------------------------------------- figures


def test_a_figure_cannot_be_built_without_a_source() -> None:
    """The entire mechanism, asserted rather than trusted.

    If this ever passes with one argument, every other guarantee on the page
    becomes a promise instead of a property.
    """
    with pytest.raises(TypeError):
        Figure(42)  # type: ignore[call-arg]


def test_a_figure_with_a_source_renders_its_citation() -> None:
    figure = Figure(3, Source.table("agents", "department = executive"))
    assert figure.render() == "3"
    assert "agents" in figure.title()
    assert "department = executive" in figure.title()


def test_absent_is_not_zero() -> None:
    """A measurement of zero and the absence of one are different sentences."""
    measured = Figure(0, Source.table("meetings", "closed"))
    unmeasured = Figure.absent("the strategy record arrives in M8")

    assert measured.render() == "0"
    assert measured.present
    assert unmeasured.render() == "NO DATA"
    assert not unmeasured.present
    assert "M8" in unmeasured.title()


def test_a_derived_figure_must_cite_what_it_read() -> None:
    with pytest.raises(ValueError, match="must cite what it was derived from"):
        Figure.derived(5, how="sum", sources=[])


def test_a_decimal_renders_as_declared_not_as_padded() -> None:
    figure = Figure(Decimal("0.11000000"), Source.table("hypotheses"))
    assert figure.render() == "0.11"


# ------------------------------------------------------------------ layout


def test_every_department_in_the_registry_has_a_room() -> None:
    """The building is generated, so it cannot fall behind the company."""
    facility = build_facility()
    for department in DEPARTMENTS:
        assert facility.for_department(department) is not None, department


def test_every_desk_in_the_registry_has_a_bay() -> None:
    facility = build_facility()
    assert {bay.desk for bay in facility.bays} == set(DESKS)


def test_the_sealed_rooms_have_no_corridor() -> None:
    """You cannot walk into a process boundary.

    Asserted geometrically: no corridor endpoint touches either room's box.
    A door drawn into the Registry would be a drawn way around a rule.
    """
    facility = build_facility()
    sealed = [room for room in facility.rooms if room.kind is RoomKind.SEALED]
    assert {room.room_id for room in sealed} == {"registry", "vault"}

    for room in sealed:
        assert not room.reachable
        for corridor in facility.corridors:
            for x, y in ((corridor.x1, corridor.y1), (corridor.x2, corridor.y2)):
                inside = (
                    room.x <= x <= room.x + room.w and room.y <= y <= room.y + room.h
                )
                assert not inside, f"a corridor reaches {room.room_id}"


def test_the_layout_is_deterministic() -> None:
    """Two builds of the same state produce the same picture, byte for byte."""
    assert build_facility() == build_facility()


def test_rooms_grow_downward_in_fixed_columns() -> None:
    facility = build_facility()
    rooms = [room for room in facility.rooms if room.kind is RoomKind.DEPARTMENT]
    columns = {room.x for room in rooms}
    assert len(columns) == COLUMNS


# --------------------------------------------------- the drawing is legible


def test_no_two_captions_overlap(company: Runtime) -> None:
    """The label-overlap acceptance check.

    Overlapping text fails exactly where the drawing is densest, which is where
    the information is.
    """
    facility = build_facility()
    with company.database.session() as session:
        statuses = proj.room_statuses(session)
    drawing = render_facility(facility, statuses)

    hits = collisions(drawing.labels)
    assert not hits, [(a.content, b.content) for a, b in hits]
    assert len(drawing.labels) > 20, "the facility should be labelled, not bare"


def test_the_overlap_check_actually_detects_an_overlap() -> None:
    """A test that never fails is not a test."""
    a = Label("QUANTITATIVE RESEARCH", 10, 10)
    b = Label("MARKET INTELLIGENCE", 14, 12)
    assert collisions([a, b])
    assert not collisions([a, Label("FAR AWAY", 900, 900)])


def test_label_boxes_follow_their_anchor() -> None:
    start = Label("ABCD", 100, 50, anchor=Anchor.START)
    end = Label("ABCD", 100, 50, anchor=Anchor.END)
    assert start.box[0] < start.box[2]
    assert end.box[2] <= start.box[2]


def test_the_facility_drawing_references_nothing_external(company: Runtime) -> None:
    """Vector only, no binary assets, nothing fetched."""
    facility = build_facility()
    with company.database.session() as session:
        statuses = proj.room_statuses(session)
    svg = render_facility(facility, statuses).render()

    assert "<image" not in svg
    assert "url(" not in svg
    urls = set(re.findall(r"https?://[^\"' <]+", svg))
    # The SVG namespace is an identifier, never fetched.
    assert urls <= {"http://www.w3.org/2000/svg"}


# -------------------------------------------------------------- the record


def test_an_unstaffed_department_is_drawn_not_hidden(runtime: Runtime) -> None:
    """A company that hides its empty rooms is describing an org chart."""
    with runtime.database.session() as session:
        statuses = proj.room_statuses(session)

    assert set(statuses) == set(DEPARTMENTS)
    assert all(status.plate == "UNSTAFFED" for status in statuses.values())
    assert all(status.headcount.value == 0 for status in statuses.values())


def test_a_room_reads_working_when_its_staff_are(company: Runtime) -> None:
    with company.database.session() as session:
        agent = company.roster.by_handle(session, "QUANT")
        company.roster.set_state(session, agent.ref, AgentState.WORKING)
        statuses = proj.room_statuses(session)

    research = statuses[Department.QUANTITATIVE_RESEARCH]
    assert research.plate == "WORKING"
    assert research.busy
    assert statuses[Department.TRADING_OPERATIONS].plate == "IDLE"


def test_measured_zero_and_unmeasured_are_different_figures(company: Runtime) -> None:
    """The distinction the whole `Figure` type exists to hold.

    Strategies and alerts illustrated this until M8 and M9 built them; they now
    legitimately read `0`, which is the *right* answer and a different sentence
    from `NO DATA`. The principle is unchanged, so the test now uses a figure
    that is still genuinely unmeasured.
    """
    with company.database.session() as session:
        desk = proj.desk_view(session, next(iter(DESKS)))
        status = proj.company_status(session, chain_ok=True, chain_detail="ok")
        agent = proj.agent_view(session, company.roster.by_handle(session, "QUANT").ref)

    # Measured, and the measurement is zero.
    for figure in (desk.strategies, status.alerts, status.missions_open):
        assert figure.present
        assert figure.render() == "0"

    # Not measured. Never rendered as a zero.
    assert agent is not None
    assert not agent.observations.present
    assert agent.observations.render() == "NO DATA"
    assert not agent.brier.present, "no forecast this agent made has been scored"


def test_nothing_on_the_station_is_a_placeholder(company: Runtime) -> None:
    """An empty not-yet map is a checkable statement, not a comment."""
    assert proj._NOT_YET == {}


def test_every_company_figure_names_a_real_source(company: Runtime) -> None:
    with company.database.session() as session:
        status = proj.company_status(session, chain_ok=True, chain_detail="ok")

    for name, figure in status.figures():
        assert figure.source.kind in set(SourceKind), name
        assert figure.title(), name


def test_the_timeline_is_a_projection_of_the_ledger(company: Runtime) -> None:
    with company.database.session() as session:
        entries = proj.timeline(session, limit=500)
        total = company.ledger.count(session)

    assert entries
    assert [entry.seq for entry in entries] == sorted(entry.seq for entry in entries)
    assert entries[-1].seq == total


def test_the_timeline_can_be_read_forward_from_a_cursor(company: Runtime) -> None:
    """What the live stream does on every poll."""
    with company.database.session() as session:
        everything = proj.timeline(session, limit=500)
        cutoff = everything[len(everything) // 2].seq
        newer = proj.timeline(session, since=cutoff)

    assert newer
    assert all(entry.seq > cutoff for entry in newer)


# --------------------------------------------------------------- the pages


def test_the_facility_page_renders_the_building(reviewed: Runtime) -> None:
    html = _get(_app(reviewed), "/")
    assert "<svg" in html
    assert "QUANTITATIVE RESEARCH" in html
    assert "NO CORRIDOR" in html


def test_an_unknown_path_is_a_404_that_says_so(reviewed: Runtime) -> None:
    response = _app(reviewed).handle("/nonsense", {})
    assert response.status == 404
    assert "not in the record" in response.body.decode("utf-8")


def test_a_missing_subject_is_not_invented(reviewed: Runtime) -> None:
    response = _app(reviewed).handle("/hypothesis/HYP-9999", {})
    assert response.status == 404
    assert "HYP-9999" in response.body.decode("utf-8")


def test_the_station_serves_only_get() -> None:
    """Read-only as a property of the code, not a promise in a docstring."""
    from aurelis.station.app import _Handler

    assert hasattr(_Handler, "do_GET")
    assert not any(
        name.startswith("do_") and name != "do_GET" for name in vars(_Handler)
    )


def test_agent_prose_cannot_become_markup(company: Runtime) -> None:
    """An agent writes text. Text must never be able to become tags."""
    with company.database.session() as session:
        quant = company.roster.by_handle(session, "QUANT").ref
        company.research.propose(
            session,
            claim="<script>alert('x')</script> momentum works",
            author=quant,
            minimum_effect=Decimal("0.05"),
            primary_metric="sharpe",
            family="strategy.momentum.crypto",
        )
    html = _get(_app(company), "/research")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


# ------------------------------------------------------------- acceptance


def test_the_whole_review_is_legible_without_a_terminal(reviewed: Runtime) -> None:
    """M7 acceptance.

    What happened, who did it, what it cost, what was decided, who disagreed
    and what failed — each read off a rendered page rather than a log.
    """
    app = _app(reviewed)

    # What happened, and what failed.
    hypothesis = _get(app, "/hypothesis/HYP-0001")
    assert "REFUTED" in hypothesis
    assert "survivorship" in hypothesis
    assert "0.64507263" in hypothesis, "the measurement that killed it"
    assert "UPHELD" in hypothesis

    # Why the company believed it in the first place: provenance, in full.
    assert "REG-0001" in hypothesis
    assert "criteria committed before the run" in hypothesis
    assert "DATA FINGERPRINT" in hypothesis
    assert "ENGINE" in hypothesis, "who computed the numbers"

    # Who did it.
    assert "AG-" in hypothesis
    agent = _get(app, "/agent/AG-0006")
    assert "Can see" in agent or "CAN SEE" in agent.upper()
    assert "Can write" in agent or "CAN WRITE" in agent.upper()

    # What was decided, and who disagreed.
    meeting = _get(app, "/meeting/MTG-0001")
    assert "Decision and dissent" in meeting
    assert "Transcript" in meeting
    assert "dissent" in meeting.lower()

    # What it cost.
    assert "cost" in meeting.lower()

    # And the failure is a first-class room, not a hidden tab.
    graveyard = _get(app, "/graveyard")
    assert "HYP-0001" in graveyard
    assert "refuted" in graveyard.lower()


def test_every_figure_on_the_front_page_carries_a_title(reviewed: Runtime) -> None:
    """The checkable form of "nothing on this page was typed"."""
    html = _get(_app(reviewed), "/")
    figures = re.findall(r"<span class='v figure[^']*' title='([^']*)'>", html)
    assert figures
    assert all(title.strip() for title in figures)


# ------------------------------------------------------------ sealed build


def test_the_sealed_build_is_one_file_that_fetches_nothing(
    reviewed: Runtime, tmp_path: Path
) -> None:
    out = tmp_path / "station.html"
    with reviewed.database.session():
        pass
    report = build_sealed(reviewed, out)
    html = out.read_text(encoding="utf-8")

    assert out.exists()
    assert report.bytes_written > 10_000
    assert "<link" not in html
    assert "<img" not in html
    assert "<script" not in html
    urls = set(re.findall(r"https?://[^\"' <]+", html))
    assert urls <= {"http://www.w3.org/2000/svg"}


def test_the_sealed_build_stamps_the_chain_and_the_head(
    reviewed: Runtime, tmp_path: Path
) -> None:
    """A snapshot of a broken chain must not look like a sound one."""
    report = build_sealed(reviewed, tmp_path / "station.html")
    html = (tmp_path / "station.html").read_text(encoding="utf-8")

    assert report.head_seq > 0
    assert report.chain_ok
    assert "CHAIN VERIFIED" in html
    assert f"seq {report.head_seq}" in html
    assert "SEALED SNAPSHOT" in html


def test_the_sealed_build_does_not_promise_pages_it_lacks(
    reviewed: Runtime, tmp_path: Path
) -> None:
    """Links into detail pages become plain text rather than dead links."""
    html = (
        build_sealed(reviewed, tmp_path / "station.html").path.read_text(
            encoding="utf-8"
        )
    )
    hrefs = set(re.findall(r"<a href='([^']*)'", html))
    assert hrefs, "the in-page nav should still be linked"
    assert all(href.startswith("#") for href in hrefs), sorted(hrefs)
    assert "HYP-0001" in html, "the reference is still readable as text"


def test_the_sealed_build_carries_the_graveyard(
    reviewed: Runtime, tmp_path: Path
) -> None:
    html = (
        build_sealed(reviewed, tmp_path / "station.html").path.read_text(
            encoding="utf-8"
        )
    )
    assert "The Graveyard" in html
    assert "HYP-0001" in html


# ---------------------------------------------------------------- serving


def test_the_server_starts_and_answers(reviewed: Runtime) -> None:
    """The real socket, not a stand-in."""
    import urllib.request

    server = serve(reviewed, port=0, background=True)
    try:
        with urllib.request.urlopen(f"{server.url}", timeout=10) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
        assert "AURELIS" in body
        assert "<svg" in body
    finally:
        server.stop()


def test_there_is_no_way_to_draw_text_except_through_a_label() -> None:
    """The overlap check is only worth having if nothing can bypass it.

    A raw text primitive — even one meant for plant markings — is a caption
    waiting to be added that the check would never measure.
    """
    from aurelis.station import svg

    assert "text" not in svg.__all__
    assert not hasattr(svg, "text")
    assert hasattr(svg.Label, "box")
