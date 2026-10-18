"""The Office: the company drawn as the building it works in (M61).

The art is Nullius's station, carried over (``art.py`` and the templates).
The rooms are Aurelis's departments, with the Control Room at the centre
(``map.py``), and what moves is read off the record (``live.py``). The
station serves it at ``/``. The older facility page is at ``/facility``.
"""

from __future__ import annotations

import json
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from aurelis.office.art import ACCENTS, CEIL, SLAB, WALL, plan, skin_of
from aurelis.office.map import ROOMS

__all__ = ["environment", "render_office"]


def environment() -> Environment:
    env = Environment(
        loader=PackageLoader("aurelis.office", "templates"),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["accent"] = lambda name: ACCENTS.get(name, ACCENTS["white"])
    # parts.html's counter plates read a backing colour; the Office draws none,
    # but the macro file must still load.
    env.globals["backing_colour"] = lambda name: "var(--warn)"
    return env


def _rooms_json() -> str:
    body = json.dumps(
        [
            {
                "room_id": room.room_id,
                "index": f"{index:02d}",
                "name": room.name,
                "accent_hex": ACCENTS.get(room.accent, ACCENTS["white"]),
                "face": skin_of(room.room_id)[0],
                "frame": skin_of(room.room_id)[1],
            }
            for index, room in enumerate(ROOMS, start=1)
        ],
        separators=(",", ":"),
    )
    for character, escape in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        body = body.replace(character, escape)
    return body


def render_office(session: Any, now: Any) -> str:
    """The Office as one HTML page: the drawn building and its live layer."""
    from aurelis.office.live import people
    from aurelis.station.health import company_health

    layout = plan(people(session))
    return (
        environment()
        .get_template("office.html")
        .render(
            plan=layout,
            world=layout["world"],
            rooms=ROOMS,
            accents=ACCENTS,
            CEIL=CEIL,
            SLAB=SLAB,
            wall=WALL,
            health=company_health(session, now),
            rooms_json=_rooms_json(),
        )
    )
