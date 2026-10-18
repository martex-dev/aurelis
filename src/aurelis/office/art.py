"""Drawing the Office (M61).

Carried over from Nullius's station (``nullius/station/render.py``), which the
operator called "very close to my idea". It keeps Nullius's side-on cutaway
and its materials, furniture, lighting and people. The constants and the
furniture placement below are Nullius's, with furniture chosen for
Aurelis's rooms.

Aurelis's own code is at the bottom: who stands in which room (the agents the
record says are employed there), the hallways and lifts built from the plan's
links, and :func:`plan`, which hands the template every coordinate.

**What the art may and may not do.** The rule is the same as in Nullius. The
furniture is decoration, placed by a hash of the room's id so two builds draw
the same picture. The people are not decoration. A figure is drawn for every
agent on the payroll and for nobody else. It moves only while the record says
that agent is working (``station/activity.py``), and between wakes it stands
at its post.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aurelis.office.map import CONTROL, LINKS, ROOMS, OfficeRoom, room_named

__all__ = [
    "ACCENTS",
    "FURNITURE",
    "WORLD",
    "OfficeAgent",
    "build_of",
    "plan",
    "skin_of",
]

#: underline and the edge of every figure agree with the room you came from.
FACES: dict[str, str] = {
    "serif": "Georgia, 'Iowan Old Style', 'Palatino Linotype', Palatino, serif",
    "slab": "Rockwell, 'Roboto Slab', 'Bookman Old Style', Georgia, serif",
    "mono": "ui-monospace, 'Cascadia Mono', 'SF Mono', Menlo, Consolas, monospace",
    "narrow": "'Arial Narrow', 'Roboto Condensed', 'Liberation Sans Narrow', "
    "'Helvetica Neue', sans-serif",
    "humanist": "'Trebuchet MS', 'Segoe UI', Candara, Optima, sans-serif",
    "grotesk": "Inter, 'Segoe UI', system-ui, 'Helvetica Neue', Arial, sans-serif",
}

#: (face, frame) per department.
SKINS: dict[str, tuple[str, str]] = {
    "control": ("grotesk", "board"),
    "market_intelligence": ("humanist", "board"),
    "quantitative_research": ("mono", "console"),
    "strategy_laboratory": ("narrow", "bay"),
    "portfolio_and_risk": ("slab", "ledger"),
    "trading_operations": ("mono", "console"),
    "executive": ("serif", "sheet"),
    "knowledge_and_memory": ("serif", "sheet"),
    "audit_and_governance": ("narrow", "bay"),
    "institutional_governance": ("slab", "ledger"),
    "infrastructure": ("mono", "console"),
}


def skin_of(room_id: str) -> tuple[str, str]:
    """The face and the frame this department's sheet is set in."""
    face, frame = SKINS.get(room_id, ("grotesk", "board"))
    return FACES[face], frame


#: Room accent, as a hue the whole page agrees on: map, panel and chart alike.
ACCENTS: dict[str, str] = {
    "violet": "#a78bfa",
    "amber": "#fbbf24",
    "cyan": "#22d3ee",
    "teal": "#2dd4bf",
    "green": "#4ade80",
    "blue": "#60a5fa",
    "orange": "#fb923c",
    "indigo": "#818cf8",
    "slate": "#8b98ac",
    "white": "#e8edf5",
    "magenta": "#f472b6",
    "gold": "#facc15",
    "olive": "#a3b346",
    "crimson": "#f87171",
    "beacon": "#ffd479",
}

#: What a thing is made of, as a body colour and the colour of its shadowed
#: side. Until M28 every fixture in the station was drawn in two greys and the
#: room's own hue, which is why a workbench and a filing cabinet and a reactor
#: were the same object at different proportions. A material is not a claim
#: about the institution -- it is the difference between a drawing of a room and
#: a diagram of one.
MATERIALS: dict[str, tuple[str, str]] = {
    "steel": ("var(--m-steel)", "var(--m-steel-2)"),
    "enamel": ("var(--m-enamel)", "var(--m-enamel-2)"),
    "wood": ("var(--m-wood)", "var(--m-wood-2)"),
    "brass": ("var(--m-brass)", "var(--m-brass-2)"),
    "glass": ("var(--m-glass)", "var(--m-glass-2)"),
    "rubber": ("var(--m-rubber)", "var(--m-rubber-2)"),
    "paint": ("var(--m-paint)", "var(--m-paint-2)"),
    "dark": ("var(--fix)", "var(--fix-2)"),
}

#: What each kind of thing is made of.
TONES: dict[str, str] = {
    "rack": "steel",
    "cabinet": "enamel",
    "shelf": "wood",
    "board": "dark",
    "screen": "glass",
    "console": "steel",
    "desk": "wood",
    "bench": "steel",
    "table": "enamel",
    "crate": "wood",
    "terminal": "glass",
    "plinth": "brass",
    "vent": "steel",
    "bigboard": "glass",
    "conduit": "steel",
    "sign": "dark",
    "locker": "enamel",
    "printer": "enamel",
    "chair": "rubber",
    "barrel": "paint",
    "cart": "steel",
    "cables": "dark",
    "hatch": "steel",
    "drawingtable": "wood",
    "pinboard": "wood",
    "scanner": "enamel",
    "binbank": "enamel",
    "sealpress": "brass",
    "filewall": "enamel",
    "workbench": "wood",
    "partsbin": "steel",
    "reactor": "steel",
    "coolant": "steel",
    "plotwall": "enamel",
    "scope": "glass",
    "dummy": "rubber",
    "targetboard": "paint",
    "maskcase": "glass",
    "keysafe": "steel",
    "readingdesk": "wood",
    "podium": "wood",
    "press": "steel",
    "spool": "brass",
    "vaultdoor": "steel",
    "bullion": "brass",
    "counter": "wood",
    "scales": "brass",
    "catalogue": "wood",
    "stacks": "wood",
    "orb": "glass",
    "dish": "enamel",
    "plant": "dark",
    "stool": "steel",
    "pipes": "steel",
    "poster": "paint",
}

#: How much of a thing's box is the cap on top of it rather than the face of
#: it. Seen from the side almost all of an object is its face; the cap is the
#: sliver of its top surface the eye still catches from a little above. A thing
#: lying flat on the deck -- a hatch, a coil of cable -- is nearly all cap.
HEIGHTS: dict[str, float] = {
    "rack": 0.12,
    "cabinet": 0.14,
    "locker": 0.13,
    "filewall": 0.1,
    "shelf": 0.13,
    "stacks": 0.14,
    "catalogue": 0.13,
    "maskcase": 0.12,
    "keysafe": 0.16,
    "vaultdoor": 0.1,
    "plotwall": 0.14,
    "board": 0.14,
    "pinboard": 0.14,
    "screen": 0.14,
    "targetboard": 0.14,
    "poster": 0.1,
    "sign": 0.16,
    "vent": 0.16,
    "bigboard": 0.12,
    "conduit": 0.42,
    "pipes": 0.42,
    "workbench": 0.3,
    "bench": 0.3,
    "desk": 0.3,
    "console": 0.28,
    "table": 0.34,
    "counter": 0.26,
    "readingdesk": 0.3,
    "drawingtable": 0.26,
    "printer": 0.26,
    "press": 0.2,
    "scanner": 0.16,
    "sealpress": 0.2,
    "partsbin": 0.13,
    "binbank": 0.3,
    "spool": 0.18,
    "coolant": 0.22,
    "scope": 0.24,
    "reactor": 0.12,
    "dish": 0.2,
    "orb": 0.2,
    "podium": 0.22,
    "plinth": 0.16,
    "terminal": 0.18,
    "bullion": 0.32,
    "scales": 0.2,
    "dummy": 0.2,
    "crate": 0.3,
    "barrel": 0.3,
    "cart": 0.3,
    "chair": 0.34,
    "stool": 0.36,
    "plant": 0.24,
    "hatch": 0.94,
    "cables": 0.8,
}

#: Things that light up in a colour of their own rather than the room's. A
#: pass/fail bin is green wherever it stands and a coolant line is cold
#: everywhere, and a room where every lamp agrees with every other lamp reads as
#: one object rather than as a place with equipment in it.
GLOWS: dict[str, str] = {
    "binbank": "green",
    "targetboard": "crimson",
    "coolant": "cyan",
    "reactor": "amber",
    "plant": "green",
    "bullion": "gold",
    "scales": "gold",
    "spool": "amber",
    "scope": "green",
    "maskcase": "cyan",
    "orb": "magenta",
    "bigboard": "beacon",
    "poster": "crimson",
    "dummy": "crimson",
    "sealpress": "gold",
}


# ------------------------------------------------------------------- the world

#: Plan units to drawing units. ``ROOMS`` lays the station out in a 200 by 124
#: grid, which is the right size for reasoning about adjacency and far too small
#: to draw in: at one unit to the pixel a room is twenty-six pixels across and
#: the people in it are specks. Everything below multiplies by this, so the map
#: is authored once in :mod:`~nullius.station.map` and drawn at a size that has
#: somewhere to put a console.
SCALE = 12.0

#: Wall thickness. Thick enough to have an inner edge that catches the light and
#: a doorway that reads as a gap rather than as a dashed line.
WALL = 9.0

#: Margin around the plan, where the exit plates and the callout cards live.
#: Asymmetric because the two edges are asked for different things: the record's
#: counter plates hang off the left, and the sealed column's cards have nowhere
#: to go but the right.
MARGIN_LEFT = 160.0
MARGIN_RIGHT = 160.0
MARGIN_TOP = 120.0
MARGIN_BOTTOM = 220.0

WORLD: tuple[float, float, float, float] = (
    -MARGIN_LEFT,
    -MARGIN_TOP,
    200.0 * SCALE + MARGIN_LEFT + MARGIN_RIGHT,
    124.0 * SCALE + MARGIN_TOP + MARGIN_BOTTOM,
)
"""The drawing's viewBox: the plan, scaled, with room around it for the exits."""

#: Where the interior starts, now that nothing is written on it.
CONTENT_TOP = 16.0

#: A room is a chamber seen from the side, so it has a ceiling, a back wall and
#: a floor you stand on rather than a plane you look down at. Until M31 the map
#: looked down on the floor of every room and the fixtures were laid out in four
#: bands of depth; the whole of that is gone. There is one ground line, and
#: everything in the room either stands on it or hangs above it.
CEIL = 20.0
"""The ceiling band, where the light fittings and the ducting are."""

SLAB = 22.0
"""The floor: a slab with a lit top edge, which is the line things stand on."""

HUNG_AT, HUNG_H = 0.0, 0.15
"""Where the ducts and the signage hang, as a fraction of the chamber."""

MOUNT_AT, MOUNT_H = 0.2, 0.34
"""Where a board or a screen is fixed to the back wall."""

AGENT_H = 82.0

#: How tall a thing that stands on the floor is, as a fraction of the chamber.
#: In elevation this is the whole of what tells a filing wall from a stool, so
#: it is the one table in this module that is doing real work rather than art.
STANDS: dict[str, float] = {
    "rack": 0.68,
    "filewall": 0.74,
    "cabinet": 0.56,
    "locker": 0.62,
    "shelf": 0.66,
    "stacks": 0.6,
    "catalogue": 0.56,
    "maskcase": 0.6,
    "vaultdoor": 0.74,
    "partsbin": 0.58,
    "coolant": 0.5,
    "reactor": 0.82,
    "scanner": 0.62,
    "press": 0.52,
    "spool": 0.42,
    "sealpress": 0.46,
    "console": 0.36,
    "counter": 0.36,
    "desk": 0.32,
    "readingdesk": 0.32,
    "workbench": 0.34,
    "bench": 0.34,
    "table": 0.26,
    "drawingtable": 0.4,
    "printer": 0.32,
    "podium": 0.38,
    "plinth": 0.52,
    "terminal": 0.52,
    "orb": 0.54,
    "dish": 0.54,
    "dummy": 0.52,
    "scales": 0.48,
    "scope": 0.36,
    "binbank": 0.3,
    "bullion": 0.22,
    "crate": 0.26,
    "barrel": 0.32,
    "cart": 0.26,
    "chair": 0.3,
    "stool": 0.24,
    "plant": 0.34,
    "cables": 0.09,
    "hatch": 0.05,
}

#: How much of a row a thing is entitled to. Dividing a row evenly gave a
#: stool the same frontage as a wall of filing drawers, which reads as a bar
#: chart of identical columns rather than as a room somebody laid out.
WIDE: dict[str, float] = {
    "filewall": 3.0,
    "rack": 2.6,
    "cabinet": 2.2,
    "locker": 2.2,
    "shelf": 2.6,
    "stacks": 2.4,
    "catalogue": 2.4,
    "maskcase": 2.2,
    "vaultdoor": 2.6,
    "partsbin": 2.4,
    "coolant": 2.2,
    "reactor": 2.4,
    "scanner": 2.2,
    "press": 2.4,
    "spool": 2.0,
    "sealpress": 1.5,
    "console": 2.6,
    "counter": 2.6,
    "desk": 2.6,
    "readingdesk": 2.4,
    "workbench": 2.8,
    "bench": 2.6,
    "table": 2.4,
    "drawingtable": 2.2,
    "printer": 1.8,
    "podium": 1.3,
    "plinth": 1.1,
    "terminal": 1.3,
    "orb": 1.3,
    "dish": 1.5,
    "dummy": 1.1,
    "scales": 1.3,
    "scope": 2.0,
    "binbank": 2.2,
    "bullion": 1.5,
    "crate": 1.1,
    "barrel": 0.8,
    "cart": 1.3,
    "chair": 0.8,
    "stool": 0.7,
    "plant": 0.8,
    "cables": 1.1,
    "hatch": 1.1,
    "bigboard": 3.6,
    "board": 2.6,
    "plotwall": 2.6,
    "screen": 2.2,
    "sign": 1.6,
    "poster": 1.1,
    "pinboard": 2.4,
    "targetboard": 2.4,
    "vent": 1.6,
    "conduit": 2.2,
    "pipes": 2.2,
    "keysafe": 1.6,
}

#: Things that hang on the wall instead of standing on the floor. A board that
#: stood on the floor would be a board leaning against the wall, which is a
#: different claim about the room.
MOUNTED: frozenset[str] = frozenset(
    {
        "bigboard",
        "board",
        "plotwall",
        "screen",
        "sign",
        "poster",
        "pinboard",
        "targetboard",
        "vent",
        "conduit",
        "pipes",
        "keysafe",
    }
)

#: The hallway between two rooms: as wide as the doorways it joins, so the walk
#: reads as one run of floor rather than as a line drawn between two boxes.
HALL = 62.0
HALL_WALL = 8.0

#: How wide a lane an agent paces, as a fraction of the floor, and how long one
#: length of it takes. Agents patrol their own room and never leave it: the
#: token is what moves through the station, and a role walking the corridor
#: would say something about the architecture that is not true.
PATROL_INSET = 22.0
PATROL_SECONDS = 19.0


def _rng(seed: str) -> Callable[[float, float], float]:
    """A tiny deterministic generator, so two builds draw the same station.

    Seeded from the room's own id rather than from a clock: the furniture is
    decoration, and decoration that moved between builds would make a diff of
    the page unreadable for the parts that are not.
    """
    state = 2166136261
    for character in seed:
        state = ((state ^ ord(character)) * 16777619) & 0xFFFFFFFF

    def nxt(low: float, high: float) -> float:
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return low + (high - low) * (state / 0x7FFFFFFF)

    return nxt


# ------------------------------------------------------------------- geometry


@dataclass(frozen=True, slots=True)
class Box:
    """An axis-aligned rectangle in world units."""

    x: float
    y: float
    w: float
    h: float

    def intersects(self, other: Box) -> bool:
        return (
            self.x < other.x + other.w
            and other.x < self.x + self.w
            and self.y < other.y + other.h
            and other.y < self.y + self.h
        )

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


def _inner(room: OfficeRoom) -> Box:
    """The floor: the room's rectangle inset by the thickness of its walls."""
    return Box(
        room.x * SCALE + WALL,
        room.y * SCALE + WALL,
        room.w * SCALE - 2 * WALL,
        room.h * SCALE - 2 * WALL,
    )


def _shell(room: OfficeRoom) -> Box:
    return Box(room.x * SCALE, room.y * SCALE, room.w * SCALE, room.h * SCALE)


def _usable(floor: Box) -> float:
    """How much floor is left once the nameplate and the chips have had theirs."""
    return floor.h - CONTENT_TOP - 6.0


def _band(floor: Box, at: float) -> float:
    """A point in the interior, measured down from where the labels stop."""
    return floor.y + CONTENT_TOP + _usable(floor) * at


def _chamber(room: OfficeRoom) -> Box:
    """The air inside a room: the interior less its ceiling and its floor slab.

    Everything a room contains is placed against this box -- hung from its top,
    fixed to its back, or standing on its bottom.
    """
    inner = _inner(room)
    return Box(inner.x, inner.y + CEIL, inner.w, inner.h - CEIL - SLAB)


def ground_y(room: OfficeRoom) -> float:
    """The line the people and the furniture stand on."""
    chamber = _chamber(room)
    return chamber.y + chamber.h


def lane_y(room: OfficeRoom) -> float:
    """Where the corridor crosses this room, in world units.

    The corridor is at floor level now, because in elevation a door is a hole
    in a wall at the height of the floor either side of it and a run of corridor
    is the floor between two of them.
    """
    return ground_y(room) - SLAB * 0.35


# ------------------------------------------------------------------- furniture


@dataclass(frozen=True, slots=True)
class Kit:
    """What is in a room: the fixtures against the back wall, the ones halfway
    in, and the ones the people stand at. Art, not a claim — but a room with
    nothing in it reads as a room that does nothing, which would be a claim, and
    a false one."""

    wall: tuple[str, ...]
    """Fittings against the top wall: vents, conduit runs, a sign over the door."""

    back: tuple[str, ...]
    mid: tuple[str, ...]
    front: tuple[str, ...]
    props: tuple[str, ...] = ()
    """Loose things on the floor, in the margins either side of the walk."""


#: Furniture appropriate to the work. A room absent from this mapping gets
#: :data:`DEFAULT_KIT`, so adding a room to the map draws something rather than
#: leaving an empty box.
FURNITURE: dict[str, Kit] = {
    "market_intelligence": Kit(
        ("vent", "conduit", "sign"),
        ("screen", "pinboard", "screen", "scanner"),
        ("dish", "printer"),
        ("console", "desk", "console"),
        ("stool", "plant", "cables"),
    ),
    "quantitative_research": Kit(
        ("sign", "conduit", "vent"),
        ("plotwall", "plotwall", "screen", "rack"),
        ("scope", "printer"),
        ("console", "console", "table"),
        ("stool", "plant", "cables"),
    ),
    "strategy_laboratory": Kit(
        ("vent", "sign", "pipes"),
        ("targetboard", "pinboard", "targetboard"),
        ("dummy", "drawingtable"),
        ("console", "desk"),
        ("stool", "crate", "barrel"),
    ),
    "portfolio_and_risk": Kit(
        ("sign", "conduit", "vent"),
        ("keysafe", "scales", "vaultdoor"),
        ("bullion", "counter"),
        ("console", "desk"),
        ("cart", "plant", "stool"),
    ),
    "trading_operations": Kit(
        ("vent", "pipes", "vent"),
        ("bigboard", "rack", "screen"),
        ("binbank", "printer"),
        ("console", "console", "terminal"),
        ("hatch", "stool", "cables"),
    ),
    "executive": Kit(
        ("vent", "sign", "conduit"),
        ("bigboard", "shelf", "pinboard"),
        ("podium", "catalogue", "plant"),
        ("readingdesk", "desk", "counter"),
        ("stool", "plant", "poster", "crate"),
    ),
    "control": Kit(
        ("sign", "conduit", "vent", "conduit", "vent", "conduit", "sign"),
        ("bigboard", "plotwall", "bigboard", "plotwall", "bigboard", "plotwall", "bigboard"),
        ("console", "console", "table", "console", "table", "console", "console"),
        ("console", "desk", "counter", "podium", "counter", "desk", "console"),
        ("stool", "plant", "stool", "cables", "stool", "plant", "stool", "crate"),
    ),
    "knowledge_and_memory": Kit(
        ("conduit", "vent", "conduit", "sign"),
        ("catalogue", "filewall", "catalogue", "stacks"),
        ("spool", "press"),
        ("readingdesk", "plinth"),
        ("cart", "cables", "stool"),
    ),
    "audit_and_governance": Kit(
        ("conduit", "vent", "sign"),
        ("maskcase", "filewall", "maskcase", "keysafe"),
        ("locker", "scope"),
        ("console", "readingdesk", "console"),
        ("hatch", "cables", "stool"),
    ),
    "institutional_governance": Kit(
        ("vent", "sign", "conduit"),
        ("filewall", "filewall", "filewall", "keysafe"),
        ("sealpress", "printer", "scales"),
        ("console", "counter", "console"),
        ("stool", "hatch", "poster"),
    ),
    "infrastructure": Kit(
        ("conduit", "pipes", "vent", "pipes"),
        ("rack", "reactor", "rack", "coolant"),
        ("coolant", "partsbin"),
        ("workbench", "console", "bench"),
        ("barrel", "cart", "stool"),
    ),
}

DEFAULT_KIT = Kit(
    ("vent", "conduit", "sign"),
    ("rack", "cabinet", "shelf"),
    ("crate", "shelf"),
    ("console", "desk"),
    ("stool", "cables", "plant"),
)


def _finish(fixture: dict[str, Any], accent: str) -> dict[str, Any]:
    """Give a fixture what it is made of and what colour it lights up.

    The glow is the room's own accent unless the thing means something the room
    does not get to decide: a pass bin is green in every room that has one.
    """
    kind = str(fixture["kind"])
    body, shade = MATERIALS[TONES.get(kind, "steel")]
    fixture["body"] = body
    fixture["shade"] = shade
    fixture["glow"] = ACCENTS[GLOWS.get(kind, accent)]
    # How much of the box is the face rather than the cap on top of it. Seen
    # from the side almost all of a thing is its face; the cap is the sliver of
    # its top surface you still catch because the eye is a little above it.
    fixture["z"] = round(float(fixture["h"]) * (1.0 - HEIGHTS.get(kind, 0.14)), 2)
    # A thing on the wall casts its shadow onto the wall behind it. A thing on
    # the floor casts one under itself. Drawing the second for the first is how
    # a screen ends up looking like it is standing on a plinth.
    fixture["mounted"] = kind in MOUNTED
    return fixture


def _row(
    kinds: tuple[str, ...],
    floor: Box,
    top: float,
    height: float,
    nxt: Callable[[float, float], float],
    accent: str = "slate",
) -> list[dict[str, Any]]:
    """Space a row of fixtures evenly along the floor, with a little jitter."""
    if not kinds:
        return []
    pad = 18.0
    span = floor.w - 2 * pad
    cell = span / len(kinds)
    out: list[dict[str, Any]] = []
    for index, kind in enumerate(kinds):
        # Capped as well as proportioned: a room with one thing in it should
        # hold one thing, not one thing stretched across the whole floor.
        width = min(cell * (0.62 + nxt(0.0, 0.16)), 168.0)
        out.append(
            _finish(
                {
                    "kind": kind,
                    "x": floor.x + pad + index * cell + (cell - width) / 2,
                    "y": top,
                    "w": width,
                    "h": height,
                },
                accent,
            )
        )
    return out


def _fixtures(room: OfficeRoom) -> list[dict[str, Any]]:
    """Everything in one room, placed against the chamber rather than the floor.

    Three things can happen to a fixture. It hangs from the ceiling, it is fixed
    to the back wall, or it stands on the ground line -- and if it stands, its
    height is what says what it is. A rack is two thirds of the room; a stool is
    a quarter of it. Nothing is laid out in depth any more, because there is no
    depth to lay out in: this is a cutaway, and the only axis left is up.
    """
    nxt = _rng(room.room_id)
    kit = FURNITURE.get(room.room_id, DEFAULT_KIT)
    chamber = _chamber(room)
    ground = chamber.y + chamber.h
    hue = room.accent

    # A board that stood on the floor would be a board leaning against the
    # wall, so anything that belongs on a wall is taken out of whichever row
    # named it and hung, wherever the kit happened to put it.
    hung = _hung_row(tuple(k for k in kit.wall if k in MOUNTED), chamber, nxt, hue)
    rest = tuple(k for k in kit.wall if k not in MOUNTED)
    mounted = _mounted_row(
        tuple(k for k in kit.back + kit.mid + kit.front + kit.props if k in MOUNTED),
        chamber,
        nxt,
        hue,
    )
    tall = _standing_row(
        rest + tuple(k for k in kit.back + kit.mid if k not in MOUNTED),
        chamber,
        ground,
        nxt,
        hue,
        0.0,
    )
    near = _standing_row(
        tuple(k for k in kit.front + kit.props if k not in MOUNTED),
        chamber,
        ground,
        nxt,
        hue,
        0.5,
    )

    for fixture in hung + mounted + tall:
        fixture["depth"] = "back"
    for fixture in near:
        fixture["depth"] = "front"
    return hung + mounted + tall + near


def _hung_row(
    kinds: tuple[str, ...],
    chamber: Box,
    nxt: Callable[[float, float], float],
    accent: str,
) -> list[dict[str, Any]]:
    """Ducting and signage, hung from the ceiling."""
    return _spread(kinds, chamber, chamber.y + chamber.h * HUNG_AT, chamber.h * HUNG_H, nxt, accent)


def _mounted_row(
    kinds: tuple[str, ...],
    chamber: Box,
    nxt: Callable[[float, float], float],
    accent: str,
) -> list[dict[str, Any]]:
    """Boards and screens, fixed to the back wall."""
    return _spread(
        kinds, chamber, chamber.y + chamber.h * MOUNT_AT, chamber.h * MOUNT_H, nxt, accent
    )


def _cells(kinds: tuple[str, ...], left: float, span: float) -> list[tuple[float, float]]:
    """Divide a row between its things in proportion to how wide each one is.

    An even division gives a stool the same frontage as a wall of filing
    drawers, and a row of identical columns reads as a chart rather than as a
    room somebody laid out.
    """
    weights = [WIDE.get(kind, 1.6) for kind in kinds]
    total = sum(weights) or 1.0
    out: list[tuple[float, float]] = []
    at = left
    for weight in weights:
        cell = span * weight / total
        out.append((at, cell))
        at += cell
    return out


def _spread(
    kinds: tuple[str, ...],
    chamber: Box,
    top: float,
    height: float,
    nxt: Callable[[float, float], float],
    accent: str,
) -> list[dict[str, Any]]:
    """Space a row of fixtures along the wall, each as wide as it deserves."""
    if not kinds:
        return []
    pad = 16.0
    out: list[dict[str, Any]] = []
    cells = _cells(kinds, chamber.x + pad, chamber.w - 2 * pad)
    for kind, (at, cell) in zip(kinds, cells, strict=True):
        width = min(cell * (0.8 + nxt(0.0, 0.1)), 220.0)
        out.append(
            _finish(
                {
                    "kind": kind,
                    "x": round(at + (cell - width) / 2, 2),
                    "y": round(top, 2),
                    "w": round(width, 2),
                    "h": round(height, 2),
                },
                accent,
            )
        )
    return out


def _standing_row(
    kinds: tuple[str, ...],
    chamber: Box,
    ground: float,
    nxt: Callable[[float, float], float],
    accent: str,
    offset: float,
) -> list[dict[str, Any]]:
    """Things that stand on the floor, in a line, each as tall as it is.

    The two layers are offset by half a cell so the near one breaks the line of
    the far one. A row of objects at the same width and the same spacing reads
    as a bar chart; overlapping them is what makes it a room.
    """
    if not kinds:
        return []
    pad = 10.0
    out: list[dict[str, Any]] = []
    cells = _cells(kinds, chamber.x + pad, chamber.w - 2 * pad)
    for kind, (at, cell) in zip(kinds, cells, strict=True):
        height = chamber.h * STANDS.get(kind, 0.3)
        width = min(cell * (0.86 + nxt(0.0, 0.1)), 230.0)
        left = at + (cell - width) / 2 + offset * cell * 0.18
        left = min(max(left, chamber.x + 4.0), chamber.x + chamber.w - width - 4.0)
        out.append(
            _finish(
                {
                    "kind": kind,
                    "x": round(left, 2),
                    "y": round(ground - height, 2),
                    "w": round(width, 2),
                    "h": round(height, 2),
                },
                accent,
            )
        )
    return out


def _zone(room: OfficeRoom) -> dict[str, float]:
    """The strip of floor kept clear in front of the workstations.

    In elevation this is the slab itself: a lit top edge, a dark body and a
    grating, which is what tells the eye where the ground is.
    """
    chamber = _chamber(room)
    return {
        "x": round(chamber.x, 2),
        "y": round(chamber.y + chamber.h, 2),
        "w": round(chamber.w, 2),
        "h": round(SLAB, 2),
    }


def _decals(room: OfficeRoom) -> list[dict[str, Any]]:
    """Scuffs, drains and stencilled marks: the wear a floor has because it is
    walked on. Deterministic from the room's own id, like everything else."""
    nxt = _rng(room.room_id + "-wear")
    chamber = _chamber(room)
    ground = chamber.y + chamber.h
    out: list[dict[str, Any]] = []
    for index in range(7):
        out.append(
            {
                "kind": ("scuff", "scuff", "bolt", "drain")[index % 4],
                "x": round(chamber.x + 16.0 + nxt(0.0, chamber.w - 32.0), 2),
                "y": round(ground + 5.0 + nxt(0.0, SLAB - 12.0), 2),
                "r": round(3.0 + nxt(0.0, 7.0), 2),
                "a": 0.0,
            }
        )
    return out


def _bands(boxes: list[Box]) -> list[list[Box]]:
    """Group rooms into the horizontal courses they are laid out in."""
    out: list[list[Box]] = []
    for box in sorted(boxes, key=lambda b: b.y):
        if out and abs(out[-1][0].y - box.y) < 1.0:
            out[-1].append(box)
        else:
            out.append([box])
    return out


def _stars() -> list[dict[str, Any]]:
    """The dark the station stands in. Without them the ground behind the plan
    is a flat fill, and a flat fill reads as paper rather than as somewhere the
    building is."""
    nxt = _rng("the-void")
    x0, y0, w, h = WORLD
    keep_out = Box(-40.0, -40.0, 200.0 * SCALE + 80.0, 124.0 * SCALE + 80.0)
    out: list[dict[str, Any]] = []
    while len(out) < 150:
        x, y = x0 + nxt(0.0, w), y0 + nxt(0.0, h)
        inside_x = keep_out.x <= x <= keep_out.x + keep_out.w
        inside_y = keep_out.y <= y <= keep_out.y + keep_out.h
        if inside_x and inside_y:
            continue
        out.append(
            {
                "x": round(x, 1),
                "y": round(y, 1),
                "r": round(0.7 + nxt(0.0, 1.8), 2),
                "o": round(0.12 + nxt(0.0, 0.4), 3),
            }
        )
    return out


WORKABLE: frozenset[str] = frozenset(
    {
        "console",
        "desk",
        "readingdesk",
        "workbench",
        "bench",
        "table",
        "counter",
        "drawingtable",
        "printer",
        "press",
        "scanner",
        "sealpress",
        "podium",
        "terminal",
        "scope",
        "binbank",
        "coolant",
        "partsbin",
        "filewall",
        "catalogue",
        "rack",
        "cabinet",
        "locker",
        "spool",
        "shelf",
        "stacks",
        "reactor",
        "vaultdoor",
        "keysafe",
        "maskcase",
        "plinth",
        "orb",
        "dish",
        "dummy",
        "scales",
        "bullion",
    }
)
"""Things somebody could plausibly be doing something at.

An actor that paces back and forth between two arbitrary points is a gif. An
actor that walks to a bench, works at it, walks to a console and works at that
is the same amount of animation saying something: that the room is laid out and
that the person in it has somewhere to be. The stations are the room's own
fixtures, so nobody works at a barrel or in mid-air.
"""


def _stations(room: OfficeRoom, left: float, right: float) -> list[float]:
    """Where in its own stretch of floor an actor has something to work at."""
    middles = sorted(
        fixture["x"] + fixture["w"] / 2
        for fixture in _fixtures(room)
        if str(fixture["kind"]) in WORKABLE and left <= fixture["x"] + fixture["w"] / 2 <= right
    )
    span = right - left
    # Two stations a hand's width apart is a figure shuffling on the spot, which
    # reads as worse than pacing: it looks like the animation is broken rather
    # than like somebody is busy. Below that spread, walk the slice instead.
    if len(middles) >= 2 and middles[-1] - middles[0] > max(46.0, span * 0.3):
        first, last = middles[0], middles[-1]
        between = [
            middle for middle in middles[1:-1] if middle - first > 40.0 and last - middle > 40.0
        ]
        if between:
            return [first, between[len(between) // 2], last]
        return [first, last]
    return [left + span * 0.16, right - span * 0.16]


# --------------------------------------------------------------- the people


@dataclass(frozen=True, slots=True)
class OfficeAgent:
    """One figure on the map: an employed agent, or the service itself."""

    ref: str
    handle: str
    room_id: str
    build: str
    """Which of Nullius's eleven figures draws it (``agents.html``)."""


#: Which figure each launch charter's holder is drawn as. A handle absent here
#: falls back on its department, so a newly hired agent is still somebody.
BUILDS: dict[str, str] = {
    "CEO": "director",
    "CIO": "theorist",
    "OPS": "designer",
    "INTEL": "literature",
    "LEAD-R": "theorist",
    "QUANT": "analyst",
    "ENG-R": "builder",
    "STRAT": "designer",
    "CRITIC": "skeptic",
    "VALID": "replicator",
    "RISK": "custodian",
    "PM": "analyst",
    "TRADE": "builder",
    "AUDIT": "reviewer",
    "KNOW": "literature",
    "INFRA": "builder",
    "GOV": "reviewer",
    "SERVICE": "system",
    # the specialists (M66)
    "NEWS": "literature",
    "SOCIAL": "literature",
    "TECH": "analyst",
    "MACRO": "theorist",
    "ONCHAIN": "builder",
    "FUND": "reviewer",
    "STAT": "analyst",
    "BACKTEST": "builder",
    "ML": "designer",
    "ARCH": "designer",
    "ROBUST": "replicator",
    "ADV": "skeptic",
}

_BY_DEPARTMENT: dict[str, str] = {
    "executive": "director",
    "market_intelligence": "literature",
    "quantitative_research": "analyst",
    "strategy_laboratory": "skeptic",
    "portfolio_and_risk": "custodian",
    "trading_operations": "builder",
    "audit_and_governance": "reviewer",
    "knowledge_and_memory": "literature",
    "infrastructure": "builder",
    "institutional_governance": "reviewer",
}


def build_of(handle: str, department: str) -> str:
    return BUILDS.get(handle) or _BY_DEPARTMENT.get(department, "analyst")


def _sprites(room: OfficeRoom, people: list[OfficeAgent], index: int) -> list[dict[str, Any]]:
    """One figure per person in this room, each with its own stretch of floor.

    This is Nullius's rule, kept. Two people sharing one lane walk into each
    other and draw as one shape. So the floor is divided between them, and
    each paces the workstations in its own share.
    """
    out: list[dict[str, Any]] = []
    if not people:
        return out
    nxt = _rng(room.room_id + "-staff")
    floor = _chamber(room)
    feet = floor.y + floor.h
    span = floor.w - 2 * PATROL_INSET
    share = span / len(people)
    for slot, person in enumerate(people):
        left = floor.x + PATROL_INSET + slot * share
        right = left + share - (12.0 if len(people) > 1 else 0.0)
        stations = _stations(room, left, right)
        base = stations[0]
        offsets = [station - base for station in stations]
        if len(offsets) < 3:
            offsets.append(offsets[0])
        label = person.handle.upper()
        out.append(
            {
                "ref": person.ref,
                "role": person.build,
                "label": label,
                "no": f"{index:02d}",
                "tag_w": round(len(label) * 11.0 * 0.6 + 44.0, 2),
                "turns": len(stations),
                "x": round(base, 2),
                "y": round(feet, 2),
                "h": AGENT_H,
                "stations": [round(station, 2) for station in stations],
                "s0": round(offsets[0], 2),
                "s1": round(offsets[1], 2),
                "s2": round(offsets[2], 2),
                "dur": round(PATROL_SECONDS + nxt(0.0, 9.0), 2),
                "begin": round(-nxt(0.0, 18.0), 2),
                "delay": round(nxt(0.0, 2.6), 2),
                "period": round(1.1 + nxt(0.0, 0.5), 2),
                "work": round(1.5 + nxt(0.0, 0.8), 2),
            }
        )
    return out


# ------------------------------------------------------- halls and doorways


def _horizontal(one: OfficeRoom, two: OfficeRoom) -> bool:
    return abs(one.y - two.y) < 1.0


def _halls() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Every hallway and lift in :data:`LINKS`, and the doorway each one cuts.

    A hallway joins two rooms in the same course, at the height of their floor.
    A lift joins a room to the one below it, at the middle of the narrower of
    the two. The plan is laid out so that this point is always inside the
    wider room.
    """
    halls: list[dict[str, Any]] = []
    doors: dict[str, list[dict[str, Any]]] = {room.room_id: [] for room in ROOMS}
    for first_id, second_id in LINKS:
        first, second = room_named(first_id), room_named(second_id)
        one, two = _shell(first), _shell(second)
        if _horizontal(first, second):
            left, right = (first, second) if two.x > one.x else (second, first)
            lb, rb = _shell(left), _shell(right)
            lane = lane_y(left)
            halls.append(
                {
                    "x": lb.x + lb.w,
                    "y": lane - HALL / 2,
                    "w": rb.x - (lb.x + lb.w),
                    "h": HALL,
                    "vertical": False,
                }
            )
            doors[left.room_id].append({"side": "right", "at": lane, "span": HALL})
            doors[right.room_id].append({"side": "left", "at": lane, "span": HALL})
        else:
            top, bottom = (first, second) if two.y > one.y else (second, first)
            tb, bb = _shell(top), _shell(bottom)
            narrow = tb if tb.w <= bb.w else bb
            cx = narrow.x + narrow.w / 2
            halls.append(
                {
                    "x": cx - HALL / 2,
                    "y": tb.y + tb.h,
                    "w": HALL,
                    "h": bb.y - (tb.y + tb.h),
                    "vertical": True,
                }
            )
            doors[top.room_id].append({"side": "bottom", "at": cx, "cx": cx, "span": HALL})
            doors[bottom.room_id].append({"side": "top", "at": cx, "cx": cx, "span": HALL})
    kept = [hall for hall in halls if hall["w"] > 1 and hall["h"] > 1]
    for index, hall in enumerate(kept):
        hall["index"] = index + 1
    return kept, doors


def _works() -> list[dict[str, Any]]:
    """The building between the rooms: decks between the courses, and the
    plant under the floor. It is structure, with no number on it and nothing
    to click."""
    shells = [_shell(room) for room in ROOMS]
    x0 = min(box.x for box in shells)
    x1 = max(box.x + box.w for box in shells)
    out: list[dict[str, Any]] = []
    courses = _bands(shells)
    for above, below in zip(courses, courses[1:], strict=False):
        top = max(box.y + box.h for box in above)
        bottom = min(box.y for box in below)
        out.append(
            {
                "kind": "deck",
                "x": round(x0, 2),
                "y": round(top, 2),
                "w": round(x1 - x0, 2),
                "h": round(bottom - top, 2),
            }
        )
    floor = max(box.y + box.h for box in shells)
    out.append(
        {
            "kind": "hall",
            "x": round(x0, 2),
            "y": round(floor, 2),
            "w": round(x1 - x0, 2),
            "h": 132.0,
        }
    )
    return [work for work in out if work["w"] > 2 and work["h"] > 2]


def _bounds() -> dict[str, float]:
    shells = [_shell(room) for room in ROOMS]
    boxes = [(box.x, box.y, box.w, box.h) for box in shells]
    boxes += [(w["x"], w["y"], w["w"], w["h"]) for w in _works()]
    x0 = min(x for x, _, _, _ in boxes)
    y0 = min(y for _, y, _, _ in boxes)
    x1 = max(x + w for x, _, w, _ in boxes)
    y1 = max(y + h for _, y, _, h in boxes)
    return {"x": round(x0, 2), "y": round(y0, 2), "w": round(x1 - x0, 2), "h": round(y1 - y0, 2)}


def plan(people: list[OfficeAgent]) -> dict[str, Any]:
    """Every coordinate the template draws, for the people given."""
    halls, doorways = _halls()
    by_room: dict[str, list[OfficeAgent]] = {room.room_id: [] for room in ROOMS}
    for person in people:
        by_room.setdefault(person.room_id, []).append(person)
    numbers = {room.room_id: index for index, room in enumerate(ROOMS, start=1)}
    return {
        "world": {"x": WORLD[0], "y": WORLD[1], "w": WORLD[2], "h": WORLD[3]},
        "halls": halls,
        "doorways": doorways,
        "shells": {room.room_id: _shell(room).as_dict() for room in ROOMS},
        "floors": {room.room_id: _inner(room).as_dict() for room in ROOMS},
        "chambers": {room.room_id: _chamber(room).as_dict() for room in ROOMS},
        "zones": {room.room_id: _zone(room) for room in ROOMS},
        "fixtures": {room.room_id: _fixtures(room) for room in ROOMS},
        "decals": {room.room_id: _decals(room) for room in ROOMS},
        "sprites": {
            room.room_id: _sprites(room, by_room.get(room.room_id, []), numbers[room.room_id])
            for room in ROOMS
        },
        "numbers": numbers,
        "works": _works(),
        "stars": _stars(),
        "bounds": _bounds(),
        "control": CONTROL,
        "lamps": [
            {
                "room_id": room.room_id,
                "x": _shell(room).x + _shell(room).w / 2,
                "y": _shell(room).y + _shell(room).h / 2,
                "r": max(_shell(room).w, _shell(room).h) * 0.62,
                "accent": room.accent,
            }
            for room in ROOMS
        ],
    }
