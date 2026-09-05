"""The facility drawing, and the shell every page sits in.

Rooms are drawn as **cutaways** — a chamber seen from the side, with ceiling,
back wall, floor, and the plant that runs the building between them. None of
the plant carries a number, because none of it records anything: a pipe with a
reading on it would be decoration pretending to be instrumentation, which is
the specific failure `CLAUDE.md` §34 names.

Status is carried by three colours and one word. A room reads ``WORKING``,
``IN MEETING``, ``IDLE``, ``UNSTAFFED`` or ``NO DATA``, and nothing else — the
vocabulary is small so that a glance is reliable. A department with no agents
gets an unlit room, drawn at full size, because a company that hides its empty
rooms is describing an org chart rather than an organisation.

Every caption goes through :class:`~aurelis.station.svg.Label`, which knows its
own box, and a test asserts that no two boxes in the rendered facility
intersect. Overlapping text is not a cosmetic problem: it fails exactly where
the drawing is densest, which is where the information is.
"""

from __future__ import annotations

from aurelis.org.departments import Department
from aurelis.org.desks import DeskStatus
from aurelis.station.figures import Figure
from aurelis.station.layout import Bay, Facility, Fixture, Room, RoomKind, Strip
from aurelis.station.projections import CompanyStatus, RoomStatus
from aurelis.station.svg import (
    Anchor,
    Drawing,
    Label,
    Palette,
    escape_text,
    line,
    rect,
)

__all__ = ["STYLE", "facility_svg", "page", "render_facility"]

def render_facility(
    facility: Facility,
    statuses: dict[Department, RoomStatus],
    palette: Palette | None = None,
) -> Drawing:
    """Draw the building. Returns the drawing so its labels can be checked."""
    colours = palette or Palette()
    drawing = Drawing(facility.width, facility.height, colours)

    drawing.add(rect(0, 0, facility.width, facility.height, fill=colours.ground))

    # Corridors first, so rooms sit on top of them.
    for corridor in facility.corridors:
        drawing.add(
            line(
                corridor.x1,
                corridor.y1,
                corridor.x2,
                corridor.y2,
                stroke=colours.plant,
                width=3,
            )
        )

    for room in facility.rooms:
        status = statuses.get(room.department) if room.department else None
        _draw_room(drawing, room, status, colours)

    for strip in facility.strips:
        _draw_strip(drawing, strip, colours)

    for bay in facility.bays:
        _draw_bay(drawing, bay, colours)

    return drawing


def _draw_room(
    drawing: Drawing, room: Room, status: RoomStatus | None, colours: Palette
) -> None:
    sealed = room.kind is RoomKind.SEALED
    tone = colours.sealed if sealed else getattr(colours, status.tone if status else "dim")

    drawing.add(rect(room.x, room.y, room.w, room.h, fill=colours.wall))
    for fixture in room.fixtures:
        _draw_fixture(drawing, room, fixture, colours, tone)
    drawing.add(rect(room.x, room.y, room.w, room.h, stroke=colours.edge, width=1))

    # The lit strip along the ceiling is the only thing that carries status, so
    # a glance across the building reads as occupancy rather than as decor.
    drawing.add(rect(room.x + 1, room.y + 1, room.w - 2, 4, fill=tone))

    drawing.label(
        Label(
            room.title.upper(),
            room.x + 12,
            room.y + 26,
            size=12,
            weight="bold",
            fill=colours.ink,
            href="" if sealed else room.href,
            title=room.owns,
        )
    )

    if sealed:
        _draw_seal(drawing, room, colours)
        drawing.label(
            Label(
                "NO CORRIDOR",
                room.x + 12,
                room.y + 44,
                size=9,
                fill=colours.sealed,
                title=room.owns,
            )
        )
        return

    plate = status.plate if status else "NO DATA"
    drawing.label(
        Label(plate, room.x + 12, room.y + 44, size=10, fill=tone, title=room.owns)
    )
    if status is None:
        return

    drawing.label(
        Label(
            f"{status.headcount.render()} staff",
            room.x + room.w - 12,
            room.y + 44,
            size=9,
            anchor=Anchor.END,
            fill=colours.dim,
            title=status.headcount.title(),
        )
    )
    _draw_staff(drawing, room, status, colours, tone)


def _draw_staff(
    drawing: Drawing,
    room: Room,
    status: RoomStatus,
    colours: Palette,
    tone: str,
) -> None:
    """One figure per member of staff, standing on the floor.

    These are *data*, not scenery: the number of figures is the headcount, so a
    room with three people has three. Drawing a fixed crowd would be exactly
    the decoration `CLAUDE.md` §34 forbids — a picture that looks busy whatever
    the record says.
    """
    headcount = status.headcount.value
    if not isinstance(headcount, int) or headcount <= 0:
        return

    floor = room.y + room.h - 18
    shown = min(headcount, 8)
    step = (room.w - 44) // max(1, shown)

    for index in range(shown):
        x = room.x + 24 + index * step
        # Busy staff take the room's status colour; idle staff are still
        # clearly people, just unlit. Drawing them in the plant colour made
        # them read as furniture, which is the opposite of the point.
        colour = tone if status.busy else colours.dim
        # Head, torso, legs: blocky on purpose.
        drawing.add(rect(x, floor - 27, 8, 8, fill=colour))
        drawing.add(rect(x, floor - 17, 8, 11, fill=colour, opacity=0.8))
        drawing.add(rect(x + 1, floor - 5, 2, 5, fill=colour, opacity=0.6))
        drawing.add(rect(x + 5, floor - 5, 2, 5, fill=colour, opacity=0.6))

    if headcount > shown:
        drawing.label(
            Label(
                f"+{headcount - shown}",
                room.x + 24 + shown * step,
                floor - 6,
                size=9,
                fill=colours.dim,
                title=f"{headcount} staff in total; eight are drawn",
            )
        )


def _draw_seal(drawing: Drawing, room: Room, colours: Palette) -> None:
    """Hatching across a sealed room. There is no way in, so it is barred."""
    for offset in range(0, room.w + room.h, 16):
        drawing.add(
            line(
                room.x + max(0, offset - room.h),
                room.y + min(offset, room.h),
                room.x + min(offset, room.w),
                room.y + max(0, offset - room.w),
                stroke=colours.sealed,
                width=1,
                dash="2 6",
            )
        )


def _draw_fixture(
    drawing: Drawing, room: Room, fixture: Fixture, colours: Palette, tone: str
) -> None:
    """Plant. Carries no reading, ever.

    A pipe with a number on it would be decoration pretending to be
    instrumentation, and a reader who learned to trust one would have learned
    the wrong lesson about the rest of the page.
    """
    x, y = room.x + fixture.x, room.y + fixture.y
    if fixture.shape == "backwall":
        drawing.add(rect(x, y, fixture.w, fixture.h, fill=colours.plate))
    elif fixture.shape == "rib":
        drawing.add(
            line(x, y, x, y + fixture.h, stroke=colours.wall, width=2, dash="6 5")
        )
    elif fixture.shape == "floor":
        drawing.add(rect(x, y, fixture.w, fixture.h, fill=colours.plant))
        drawing.add(rect(x, y + fixture.h, fixture.w, 3, fill=colours.edge))
    elif fixture.shape == "ceiling":
        drawing.add(rect(x, y, fixture.w, fixture.h, fill=colours.plate))
    elif fixture.shape == "console":
        drawing.add(rect(x, y, fixture.w, fixture.h, fill=colours.edge))
        drawing.add(
            rect(x + 3, y + 3, fixture.w - 6, fixture.h - 8, fill=colours.ground)
        )
        drawing.add(
            rect(
                x + 5,
                y + 5,
                max(3, (fixture.w - 10) // 2),
                2,
                fill=tone,
                opacity=0.7,
            )
        )
    elif fixture.shape == "lamp":
        drawing.add(rect(x, y, fixture.w, fixture.h, fill=colours.edge))
        drawing.add(rect(x + 2, y + fixture.h, fixture.w - 4, 2, fill=tone, opacity=0.5))
    elif fixture.shape == "pipe":
        drawing.add(
            line(x, y, x + fixture.w, y, stroke=colours.edge, width=fixture.h + 2)
        )


def _draw_strip(drawing: Drawing, strip: Strip, colours: Palette) -> None:
    drawing.add(rect(strip.x, strip.y, strip.w, strip.h, fill=colours.plate))
    drawing.add(rect(strip.x, strip.y, strip.w, strip.h, stroke=colours.edge, width=1))
    drawing.label(
        Label(
            strip.title.upper(),
            strip.x + 12,
            strip.y + 16,
            size=10,
            weight="bold",
            fill=colours.ink,
            href=strip.href,
        )
    )


def _draw_bay(drawing: Drawing, bay: Bay, colours: Palette) -> None:
    live = bay.status is DeskStatus.ACTIVE
    tone = colours.working if live else colours.dim
    drawing.add(rect(bay.x, bay.y, bay.w, bay.h, fill=colours.wall))
    drawing.add(rect(bay.x, bay.y, bay.w, 2, fill=tone, opacity=0.85))
    drawing.label(
        Label(
            bay.name.upper(),
            bay.x + 5,
            bay.y + 18,
            size=9,
            fill=colours.ink if live else colours.dim,
            href=bay.href,
            title=f"{bay.name}: {bay.status.value}",
        )
    )


def facility_svg(facility: Facility, statuses: dict[Department, RoomStatus]) -> str:
    return render_facility(facility, statuses).render()


# ------------------------------------------------------------------ shell

STYLE = """
:root {
  --ground:#0b0e13; --plate:#141922; --wall:#1d2430; --edge:#2b3644;
  --plant:#39465a; --ink:#c6d2e2; --dim:#7b8aa0;
  --ok:#5ad1a0; --warn:#e0b341; --bad:#d4636b; --sealed:#6f5ac9;
}
* { box-sizing: border-box; }
body {
  margin:0; background:var(--ground); color:var(--ink);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size:13px; line-height:1.5;
}
a { color:var(--ink); text-decoration:none; border-bottom:1px solid var(--plant); }
a:hover { color:#fff; border-bottom-color:var(--ok); }
header.bar {
  position:sticky; top:0; z-index:5; background:var(--plate);
  border-bottom:1px solid var(--edge); padding:8px 16px;
  display:flex; gap:18px; align-items:center; flex-wrap:wrap;
}
header.bar .brand { font-weight:700; letter-spacing:2px; }
header.bar nav { display:flex; gap:12px; margin-left:auto; flex-wrap:wrap; }
.stats { display:flex; flex-wrap:wrap; gap:8px 22px; }
.stat { display:flex; gap:6px; align-items:baseline; }
.stat .k { color:var(--dim); font-size:11px; text-transform:uppercase; }
.stat .v { font-weight:700; }
.nodata { color:var(--dim); font-style:italic; }
main { padding:16px; max-width:1180px; margin:0 auto; }
h1 { font-size:18px; letter-spacing:1px; margin:0 0 4px; }
h2 { font-size:13px; letter-spacing:1px; color:var(--dim);
     text-transform:uppercase; margin:22px 0 8px;
     border-bottom:1px solid var(--edge); padding-bottom:4px; }
.panel { background:var(--plate); border:1px solid var(--edge); padding:12px; margin-bottom:12px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:10px; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th { text-align:left; color:var(--dim); font-weight:400; text-transform:uppercase;
     font-size:10px; letter-spacing:1px; border-bottom:1px solid var(--edge); padding:5px 8px; }
td { padding:5px 8px; border-bottom:1px solid #1a212c; vertical-align:top; }
tr:hover td { background:#171d27; }
.pill { display:inline-block; padding:1px 7px; border:1px solid var(--edge);
        font-size:10px; letter-spacing:1px; text-transform:uppercase; }
.pill.ok { color:var(--ok); border-color:var(--ok); }
.pill.warn { color:var(--warn); border-color:var(--warn); }
.pill.bad { color:var(--bad); border-color:var(--bad); }
.pill.dim { color:var(--dim); }
.figure { border-bottom:1px dotted var(--plant); cursor:help; }
.facility { display:block; margin:0 auto; max-width:100%; height:auto; }
.timeline { font-size:12px; }
.timeline li { list-style:none; display:grid;
               grid-template-columns:58px 92px 150px 1fr; gap:10px;
               padding:3px 0; border-bottom:1px solid #161c25; }
.timeline .seq { color:var(--dim); }
.timeline .kind { color:var(--ok); }
.turn { border-left:2px solid var(--edge); padding:6px 10px; margin:8px 0; }
.turn.opposes { border-left-color:var(--bad); }
.turn.supports { border-left-color:var(--ok); }
.turn .who { color:var(--dim); font-size:11px; }
.mono { color:var(--dim); font-size:11px; word-break:break-all; }
.banner { border:1px solid var(--warn); color:var(--warn); padding:6px 10px; margin-bottom:12px; }
.banner.ok { border-color:var(--ok); color:var(--ok); }
footer { color:var(--dim); font-size:11px; padding:20px 16px; text-align:center; }
"""

_SSE = """
<script>
(function () {
  if (!window.EventSource) return;
  var since = document.body.dataset.seq || "0";
  var es = new EventSource("/events?since=" + since);
  var dot = document.getElementById("live");
  function mark(text, cls) { if (dot) { dot.textContent = text; dot.className = cls; } }
  es.onopen = function () { mark("LIVE", "pill ok"); };
  es.onerror = function () { mark("OFFLINE", "pill bad"); };
  es.onmessage = function (event) {
    var data = JSON.parse(event.data);
    if (!data.entries || !data.entries.length) return;
    var list = document.getElementById("timeline");
    if (list) {
      data.entries.forEach(function (entry) {
        var li = document.createElement("li");
        li.innerHTML =
          '<span class="seq">' + entry.seq + '</span>' +
          '<span>' + entry.at + '</span>' +
          '<span class="kind">' + entry.kind + '</span>' +
          '<span>' + entry.actor + ' &middot; ' + entry.subject + '</span>';
        list.appendChild(li);
      });
      while (list.children.length > 200) list.removeChild(list.firstChild);
      document.body.dataset.seq = data.entries[data.entries.length - 1].seq;
    }
  };
})();
</script>
"""


def page(
    title: str,
    body: str,
    *,
    status: CompanyStatus | None = None,
    mode: str = "live",
    seq: int = 0,
    live: bool = True,
) -> str:
    """The shell. Says which mode it is in, always."""
    header = _header(status, mode)
    script = _SSE if live else ""
    badge = (
        '<span id="live" class="pill dim">CONNECTING</span>'
        if live
        else '<span class="pill dim">SEALED SNAPSHOT</span>'
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape_text(title)} · Aurelis Mission Control</title>"
        f"<style>{STYLE}</style></head>"
        f"<body data-seq='{seq}'>"
        f"<header class='bar'><span class='brand'>AURELIS</span>{badge}{header}"
        "<nav>"
        "<a href='/'>facility</a><a href='/timeline'>timeline</a>"
        "<a href='/graveyard'>graveyard</a><a href='/knowledge'>knowledge</a>"
        "<a href='/research'>research</a><a href='/meetings'>meetings</a>"
        "<a href='/missions'>missions</a><a href='/agents'>agents</a>"
        "</nav></header>"
        f"<main>{body}</main>"
        "<footer>Every figure names its source — hover it. "
        "The station draws the record and computes no verdicts.</footer>"
        f"{script}</body></html>"
    )


def _header(status: CompanyStatus | None, mode: str) -> str:
    if status is None:
        return f"<span class='stat'><span class='k'>mode</span><span class='v'>{mode}</span></span>"
    parts = [
        f"<span class='stat'><span class='k'>{escape_text(key.upper())}</span>"
        f"{figure_span(figure)}</span>"
        for key, figure in status.figures()
    ]
    tone, word = ("ok", "CHAIN OK") if status.chain_ok else ("bad", "CHAIN BROKEN")
    chain = (
        f"<span class='pill {tone}' title='{escape_text(status.chain_detail)}'>"
        f"{word}</span>"
    )
    return "".join(parts) + chain


def figure_span(figure: Figure) -> str:
    """Render a figure with its citation in the hover text.

    The only way a number reaches a page. Absent figures render ``NO DATA`` in
    a muted style rather than a zero, because the two mean different things and
    a reader must be able to tell which they are looking at.
    """
    css = "v figure" if figure.present else "v figure nodata"
    return (
        f"<span class='{css}' title='{escape_text(figure.title())}'>"
        f"{escape_text(figure.render())}</span>"
    )
