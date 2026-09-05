"""The sealed snapshot: one file, no server, no external references.

A live station answers "what is happening?". A sealed build answers "what did
the record say on the day this claim was made?" — and it has to keep answering
after the database has moved on, been migrated, or been lost.

So the build is a single HTML file with every style inline, every drawing as
generated SVG, and **no request to anything**. It can be attached to a report,
committed next to a finding, or opened from a USB stick in five years. A
snapshot that fetched a stylesheet would stop rendering the day that host went
away, which is exactly the failure mode a citable artifact must not have.

Two things are stamped into it and are the reason it can be cited: the ledger
head sequence at build time, and the chain verification result. A snapshot of a
broken chain says so on its own front page rather than looking identical to a
sound one.

The live station's cross-page links become in-page anchors, so every section is
reachable without a router. Links into detail pages that the snapshot does not
contain are rendered as plain text rather than as links that go nowhere.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from aurelis.runtime import Runtime
from aurelis.station import pages
from aurelis.station import projections as proj
from aurelis.station.layout import build_facility
from aurelis.station.render import STYLE, figure_span
from aurelis.station.svg import escape_text

__all__ = ["SealedBuild", "build_sealed"]

_LINK = re.compile(r"<a href='(?!#)[^']*'>(.*?)</a>", re.DOTALL)


@dataclass(frozen=True, slots=True)
class SealedBuild:
    path: Path
    bytes_written: int
    head_seq: int
    chain_ok: bool
    chain_detail: str
    sections: tuple[str, ...]

    def describe(self) -> str:
        chain = "verified" if self.chain_ok else "BROKEN"
        return (
            f"sealed snapshot written to {self.path}\n"
            f"  size          {self.bytes_written:,} bytes, one file, no external refs\n"
            f"  ledger head   seq {self.head_seq}\n"
            f"  chain         {chain} — {self.chain_detail}\n"
            f"  sections      {', '.join(self.sections)}"
        )


def build_sealed(runtime: Runtime, out: Path, *, at: dt.datetime | None = None) -> SealedBuild:
    """Render the whole record into one self-contained page."""
    moment = at or runtime.clock.now()
    facility = build_facility()

    with runtime.database.session() as session:
        verification = runtime.ledger.verify(session)
        status = proj.company_status(
            session, chain_ok=verification.ok, chain_detail=verification.describe()
        )
        head = proj.timeline(session, limit=1)
        head_seq = head[-1].seq if head else 0

        sections = [
            ("facility", "The facility", pages.facility_page(session, facility)),
            ("timeline", "Company timeline", pages.timeline_page(session, limit=500)),
            ("research", "Research", pages.research_page(session)),
            ("graveyard", "The Graveyard", pages.graveyard_page(session)),
            ("meetings", "Meetings", pages.meetings_page(session)),
            ("missions", "Missions", pages.missions_page(session)),
            ("agents", "Staff", pages.agents_page(session)),
            ("floor", "The Floor", pages.floor_page(session)),
            ("knowledge", "Knowledge & memory", pages.knowledge_page(session)),
        ]

    nav = "".join(
        f"<a href='#{anchor}'>{escape_text(title.lower())}</a>" for anchor, title, _ in sections
    )
    header = "".join(
        f"<span class='stat'><span class='k'>{escape_text(key.upper())}</span>"
        f"{figure_span(figure)}</span>"
        for key, figure in status.figures()
    )
    chain_pill = (
        "<span class='pill ok'>CHAIN VERIFIED</span>"
        if verification.ok
        else "<span class='pill bad'>CHAIN BROKEN</span>"
    )

    body = "".join(
        f"<section id='{anchor}'><h2 class='seal'>{escape_text(title)}</h2>"
        f"{_deactivate_links(html)}</section>"
        for anchor, title, html in sections
    )

    document = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Aurelis · sealed snapshot</title>"
        f"<style>{STYLE}{_SEAL_STYLE}</style></head><body>"
        "<header class='bar'><span class='brand'>AURELIS</span>"
        "<span class='pill dim'>SEALED SNAPSHOT</span>"
        f"{chain_pill}{header}<nav>{nav}</nav></header>"
        "<main>"
        f"<div class='banner ok'>Sealed at {escape_text(moment.isoformat())} · "
        f"ledger head seq {head_seq} · {escape_text(verification.describe())}</div>"
        "<p class='mono'>One file. No stylesheet, script, font or image is "
        "fetched from anywhere, so this renders identically offline and in five "
        "years. Links into pages the snapshot does not carry are plain text "
        "rather than links that go nowhere.</p>"
        f"{body}</main>"
        "<footer>Every figure names its source — hover it. This is a snapshot "
        "of the record, not a live view.</footer>"
        "</body></html>"
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")

    return SealedBuild(
        path=out,
        bytes_written=len(document.encode("utf-8")),
        head_seq=head_seq,
        chain_ok=verification.ok,
        chain_detail=verification.describe(),
        sections=tuple(anchor for anchor, _, _ in sections),
    )


_SEAL_STYLE = """
section { border-top:1px solid var(--edge); padding-top:8px; margin-top:28px; }
h2.seal { font-size:15px; color:var(--ink); letter-spacing:2px; border:0; }
"""


def _deactivate_links(html: str) -> str:
    """Turn cross-page links into plain text.

    A snapshot with a link to ``/agent/AG-0006`` would look navigable and do
    nothing. Rendering the text without the anchor is the honest version: the
    reference is still readable, and it does not promise a page that is not in
    the file.
    """
    return _LINK.sub(r"\1", html)
