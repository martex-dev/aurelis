"""The facility, generated from the registries.

Nothing here is hand-placed. Rooms come from ``DEPARTMENTS``, floor bays come
from ``DESKS``, and fixtures are positioned by a hash of the room's own id — so
adding a department to the registry adds a room to the building, and two builds
of the same state produce the same picture, byte for byte.

That is not tidiness. A hand-drawn floor plan is a second description of the
organisation that can disagree with the first, and the disagreement is silent:
the picture keeps showing nine departments after a tenth is created, and
everyone who looks at the picture is wrong. Generating the geometry means the
building cannot be out of date with the company.

**Two rooms have no corridor.** The Registry, where preregistrations lock, and
the Vault, where the Custodian holds sealed data. You cannot walk into either,
because neither is a place — they are process boundaries, and drawing a door
into one would be drawing a way around a rule.

Coordinates are integers in an abstract unit and the drawing scales them. No
binary assets: every wall, lamp, pipe and console is generated geometry, which
keeps the page diffable and the build reproducible.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

from aurelis.org.departments import DEPARTMENTS, Department
from aurelis.org.desks import DESKS, Desk, DeskStatus

__all__ = [
    "Bay",
    "COLUMNS",
    "Facility",
    "Fixture",
    "Room",
    "RoomKind",
    "Strip",
    "build_facility",
]

COLUMNS = 3
"""Rooms per row. Rows are added as departments are, so the building grows
downward rather than being redesigned."""

_ROOM_W = 260
_ROOM_H = 150
_GAP_X = 34
_GAP_Y = 46
_MARGIN = 28
_HEADER_H = 62
_STRIP_H = 62


class RoomKind(StrEnum):
    DEPARTMENT = "department"
    SEALED = "sealed"
    """No corridor reaches it. A process boundary drawn as one."""


@dataclass(frozen=True, slots=True)
class Fixture:
    """One piece of plant: a console, a lamp, a tank, a pipe run.

    Carries no number, ever. The building's machinery records nothing, and
    fixtures that displayed values would be decoration pretending to be
    instrumentation.
    """

    shape: str
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True, slots=True)
class Room:
    """A chamber, seen in cutaway."""

    room_id: str
    title: str
    owns: str
    kind: RoomKind
    x: int
    y: int
    w: int
    h: int
    department: Department | None = None
    reachable: bool = True
    fixtures: tuple[Fixture, ...] = field(default_factory=tuple)

    @property
    def centre_x(self) -> int:
        return self.x + self.w // 2

    @property
    def centre_y(self) -> int:
        return self.y + self.h // 2

    @property
    def href(self) -> str:
        if self.department is not None:
            return f"/department/{self.department.value}"
        return f"/room/{self.room_id}"


@dataclass(frozen=True, slots=True)
class Bay:
    """One desk's bay on the trading floor."""

    desk: Desk
    name: str
    status: DeskStatus
    x: int
    y: int
    w: int
    h: int

    @property
    def href(self) -> str:
        return f"/desk/{self.desk.value}"


@dataclass(frozen=True, slots=True)
class Strip:
    """A full-width band: the floor, the graveyard."""

    strip_id: str
    title: str
    x: int
    y: int
    w: int
    h: int
    href: str


@dataclass(frozen=True, slots=True)
class Corridor:
    """A drawn connection between two rooms.

    Only between rooms that are actually reachable. The sealed rooms have
    none, and a test asserts it.
    """

    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True, slots=True)
class Facility:
    width: int
    height: int
    rooms: tuple[Room, ...]
    corridors: tuple[Corridor, ...]
    bays: tuple[Bay, ...]
    strips: tuple[Strip, ...]

    def room(self, room_id: str) -> Room | None:
        return next((r for r in self.rooms if r.room_id == room_id), None)

    def for_department(self, department: Department) -> Room | None:
        return next((r for r in self.rooms if r.department is department), None)


def build_facility() -> Facility:
    """Lay the building out. Pure, deterministic, no I/O.

    Takes no database. The building is a function of the *registries* — who
    could exist — while occupancy is a function of the record. Keeping them
    apart is what lets a department that has done nothing be drawn as an idle
    room rather than not drawn at all.
    """
    rooms: list[Room] = []

    for index, (department, spec) in enumerate(DEPARTMENTS.items()):
        column, row = index % COLUMNS, index // COLUMNS
        x = _MARGIN + column * (_ROOM_W + _GAP_X)
        y = _HEADER_H + _MARGIN + row * (_ROOM_H + _GAP_Y)
        room_id = department.value
        rooms.append(
            Room(
                room_id=room_id,
                title=spec.name,
                owns=spec.owns,
                kind=RoomKind.DEPARTMENT,
                x=x,
                y=y,
                w=_ROOM_W,
                h=_ROOM_H,
                department=department,
                reachable=True,
                fixtures=_fixtures_for(room_id, _ROOM_W, _ROOM_H),
            )
        )

    department_rows = (len(DEPARTMENTS) + COLUMNS - 1) // COLUMNS
    sealed_y = _HEADER_H + _MARGIN + department_rows * (_ROOM_H + _GAP_Y)

    for offset, (room_id, title, owns) in enumerate(
        (
            (
                "registry",
                "The Registry",
                "Where preregistrations lock. No agent may enter.",
            ),
            (
                "vault",
                "The Vault",
                "Sealed out-of-sample data, held by the Custodian.",
            ),
        )
    ):
        x = _MARGIN + offset * 2 * (_ROOM_W + _GAP_X)
        rooms.append(
            Room(
                room_id=room_id,
                title=title,
                owns=owns,
                kind=RoomKind.SEALED,
                x=x,
                y=sealed_y,
                w=_ROOM_W,
                h=_ROOM_H - 40,
                department=None,
                reachable=False,
                fixtures=_fixtures_for(room_id, _ROOM_W, _ROOM_H - 40),
            )
        )

    corridors = _corridors(rooms)

    strips_y = sealed_y + (_ROOM_H - 40) + _GAP_Y
    full_w = COLUMNS * _ROOM_W + (COLUMNS - 1) * _GAP_X
    bays = _bays(_MARGIN, strips_y, full_w)
    strips = (
        Strip("floor", "The Floor", _MARGIN, strips_y, full_w, _STRIP_H, "/floor"),
        Strip(
            "graveyard",
            "The Graveyard",
            _MARGIN,
            strips_y + _STRIP_H + _GAP_Y // 2,
            full_w,
            _STRIP_H,
            "/graveyard",
        ),
    )

    height = strips[-1].y + strips[-1].h + _MARGIN
    return Facility(
        width=full_w + 2 * _MARGIN,
        height=height,
        rooms=tuple(rooms),
        corridors=corridors,
        bays=bays,
        strips=strips,
    )


def _corridors(rooms: list[Room]) -> tuple[Corridor, ...]:
    """Connect reachable neighbours, horizontally and down each column.

    Sealed rooms are skipped on both ends, so the drawing has no line entering
    the Registry or the Vault. That absence is the point.
    """
    walkable = [room for room in rooms if room.reachable]
    by_slot = {
        (
            (room.x - _MARGIN) // (_ROOM_W + _GAP_X),
            (room.y - _HEADER_H - _MARGIN) // (_ROOM_H + _GAP_Y),
        ): room
        for room in walkable
    }

    corridors: list[Corridor] = []
    for (column, row), room in sorted(by_slot.items()):
        right = by_slot.get((column + 1, row))
        if right is not None:
            corridors.append(
                Corridor(room.x + room.w, room.centre_y, right.x, right.centre_y)
            )
        below = by_slot.get((column, row + 1))
        if below is not None:
            corridors.append(
                Corridor(room.centre_x, room.y + room.h, room.centre_x, below.y)
            )
    return tuple(corridors)


def _bays(x: int, y: int, width: int) -> tuple[Bay, ...]:
    """One bay per desk in the registry, whatever its status.

    A desk scheduled for M12 gets a bay that reads as scheduled. Drawing only
    the open desks would make the company's reach look like its current
    footprint.
    """
    desks = list(DESKS.values())
    if not desks:
        return ()
    inner = width - 16
    bay_w = inner // len(desks)
    return tuple(
        Bay(
            desk=spec.desk,
            name=spec.name,
            status=spec.status,
            x=x + 8 + index * bay_w,
            y=y + 22,
            w=bay_w - 6,
            h=_STRIP_H - 30,
        )
        for index, spec in enumerate(desks)
    )


def _fixtures_for(room_id: str, width: int, height: int) -> tuple[Fixture, ...]:
    """Plant, placed by a hash of the room's id.

    Deterministic on purpose: the same room draws the same machinery in every
    build, on every machine, so a diff of two renders shows what changed in the
    company rather than where the random number generator landed.

    Consoles are spaced evenly and only their *size* varies with the hash.
    Hashing the positions too produced clumps and gaps that read as meaningful
    when they were not — the eye looks for a reason, and there was none.
    """
    digest = hashlib.sha256(room_id.encode("utf-8")).digest()
    floor = height - 18

    fixtures: list[Fixture] = [
        Fixture("backwall", 10, 10, width - 20, floor - 12),
        Fixture("floor", 0, floor, width, 5),
        Fixture("ceiling", 0, 0, width, 8),
    ]

    ribs = 5 + digest[0] % 3
    for index in range(ribs):
        left = 16 + index * ((width - 32) // max(1, ribs - 1))
        fixtures.append(Fixture("rib", left, 12, 1, floor - 16))

    consoles = 2 + digest[1] % 3
    slot = (width - 40) // consoles
    for index in range(consoles):
        console_w = 30 + digest[(index * 5 + 2) % 32] % 20
        console_h = 15 + digest[(index * 5 + 3) % 32] % 10
        left = 22 + index * slot + (slot - console_w) // 2
        fixtures.append(Fixture("console", left, floor - console_h, console_w, console_h))

    lamps = 3
    for index in range(lamps):
        left = 30 + index * ((width - 60) // (lamps - 1))
        fixtures.append(Fixture("lamp", left - 6, 8, 12, 5))

    fixtures.append(Fixture("pipe", 0, 14 + digest[7] % 8, width, 2))
    return tuple(fixtures)
