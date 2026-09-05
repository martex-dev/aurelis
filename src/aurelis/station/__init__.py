"""Mission Control: the building the company works in.

Two rules govern everything here.

**The station draws the record, never the design.** If a number is not in the
database, the page shows `NO DATA` and says why. Every exit from every pipeline
is drawn at its true size, including the ones that read zero, and a department
that has done nothing gets an idle room rather than being left out of the
picture.

**Every figure names its source.** :class:`~aurelis.station.figures.Figure` has
no constructor that omits it, so a number cannot reach a template without
carrying the query, artifact or registry entry it came from. Hovering any
figure shows the citation. That makes "nothing on this page was typed" a
property of the type system rather than a promise in a docstring.

A corollary the modules here hold to: **the station computes no verdicts.** It
sums and counts, and marks the results as derived; it never decides anything.
A station that reached its own conclusions would be a second, unversioned
source of truth competing with the ledger.
"""

from aurelis.station.app import StationApp, StationServer, serve, station_app
from aurelis.station.build import SealedBuild, build_sealed
from aurelis.station.figures import Figure, Source, SourceKind
from aurelis.station.layout import Facility, Room, RoomKind, build_facility
from aurelis.station.render import facility_svg, page, render_facility
from aurelis.station.svg import Label, Palette, collisions

__all__ = [
    "Facility",
    "Figure",
    "Label",
    "Palette",
    "Room",
    "RoomKind",
    "SealedBuild",
    "Source",
    "SourceKind",
    "StationApp",
    "StationServer",
    "build_facility",
    "build_sealed",
    "collisions",
    "facility_svg",
    "page",
    "render_facility",
    "serve",
    "station_app",
]
