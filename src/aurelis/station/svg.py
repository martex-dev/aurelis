"""Vector primitives, and the text metric that makes labels checkable.

Every wall, lamp, pipe and caption in the station is generated geometry. No
binary assets, which keeps the page diffable, the build reproducible and the
whole facility drawable from configuration rather than from art files.

The interesting part is :class:`Label`. A drawing whose captions overlap is not
merely ugly — it is *unreadable in exactly the places where it is densest*,
which is where the information is. So labels are not strings dropped at
coordinates: each one carries its own box, and a test asserts that no two boxes
in the facility intersect.

That requires knowing how wide text is, which normally requires a font engine.
The station sidesteps it by drawing **only in a monospace face**, where advance
width is a constant multiple of the font size. The multiple is
:data:`ADVANCE_RATIO` and it is deliberately generous: the check is worth
having only if it errs toward reporting collisions that a real renderer might
just squeak past, never the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from html import escape
from itertools import combinations

__all__ = [
    "ADVANCE_RATIO",
    "Anchor",
    "Label",
    "Palette",
    "collisions",
    "escape_text",
    "rect",
    "line",
    "polyline",
    "text",
]

ADVANCE_RATIO = 0.62
"""Character advance as a fraction of font size, for the station's mono stack.

DejaVu Sans Mono, Cascadia Mono, Menlo and Consolas all sit between 0.55 and
0.61. Rounding up means the overlap test measures labels as slightly wider
than they render, so it fails toward caution.
"""

LINE_HEIGHT = 1.25


class Anchor(StrEnum):
    START = "start"
    MIDDLE = "middle"
    END = "end"


@dataclass(frozen=True, slots=True)
class Palette:
    """The station's colours, in one place so the theme is one object.

    Industrial and dark, per `CLAUDE.md` §20: a research facility seen in
    cutaway, not a SaaS dashboard. Deliberately few colours — status is carried
    by three of them and everything else is structure.
    """

    ground: str = "#0b0e13"
    plate: str = "#141922"
    wall: str = "#1d2430"
    edge: str = "#2b3644"
    plant: str = "#39465a"
    ink: str = "#c6d2e2"
    dim: str = "#7b8aa0"
    working: str = "#5ad1a0"
    attention: str = "#e0b341"
    stopped: str = "#d4636b"
    sealed: str = "#6f5ac9"


@dataclass(frozen=True, slots=True)
class Label:
    """A caption that knows how much room it takes.

    ``box`` is what the overlap test reads. Padding is included because two
    captions that touch are as unreadable as two that overlap.
    """

    content: str
    x: int
    y: int
    size: int = 11
    anchor: Anchor = Anchor.START
    fill: str = ""
    weight: str = "normal"
    href: str = ""
    title: str = ""
    padding: int = 2

    @property
    def width(self) -> float:
        return len(self.content) * self.size * ADVANCE_RATIO

    @property
    def box(self) -> tuple[float, float, float, float]:
        """``(x1, y1, x2, y2)``, with the baseline offset applied.

        SVG places text on its baseline, so the box runs from roughly the cap
        height above ``y`` to the descender below it.
        """
        width = self.width + 2 * self.padding
        if self.anchor is Anchor.MIDDLE:
            left = self.x - width / 2
        elif self.anchor is Anchor.END:
            left = self.x - width
        else:
            left = self.x - self.padding
        top = self.y - self.size * 0.8 - self.padding
        return (left, top, left + width, top + self.size * LINE_HEIGHT + 2 * self.padding)

    def render(self, palette: Palette) -> str:
        fill = self.fill or palette.ink
        weight = f' font-weight="{self.weight}"' if self.weight != "normal" else ""
        title = f"<title>{escape_text(self.title)}</title>" if self.title else ""
        body = (
            f'<text x="{self.x}" y="{self.y}" font-size="{self.size}" '
            f'text-anchor="{self.anchor.value}" fill="{fill}"{weight}>'
            f"{title}{escape_text(self.content)}</text>"
        )
        if self.href:
            return f'<a href="{escape_text(self.href)}">{body}</a>'
        return body


@dataclass(slots=True)
class Drawing:
    """An accumulating SVG document that keeps its labels for checking."""

    width: int
    height: int
    palette: Palette = field(default_factory=Palette)
    parts: list[str] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def label(self, label: Label) -> None:
        self.labels.append(label)
        self.parts.append(label.render(self.palette))

    def render(self) -> str:
        return (
            f'<svg viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}" '
            'xmlns="http://www.w3.org/2000/svg" class="facility" '
            'font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">'
            + "".join(self.parts)
            + "</svg>"
        )


def collisions(labels: list[Label]) -> list[tuple[Label, Label]]:
    """Every pair of captions whose boxes intersect.

    Returned rather than asserted so a failing test can name the offenders. An
    empty list is the only acceptable result for a rendered facility.
    """
    hits: list[tuple[Label, Label]] = []
    for left, right in combinations(labels, 2):
        ax1, ay1, ax2, ay2 = left.box
        bx1, by1, bx2, by2 = right.box
        if ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2:
            hits.append((left, right))
    return hits


def escape_text(value: str) -> str:
    """Escape for SVG/HTML.

    Applied to everything, including text the company wrote about itself. An
    agent's prose is not markup and must never be able to become markup.
    """
    return escape(str(value), quote=True)


def rect(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str = "none",
    stroke: str = "none",
    width: float = 1,
    radius: float = 0,
    opacity: float = 1,
) -> str:
    extra = f' rx="{radius}"' if radius else ""
    fade = f' opacity="{opacity}"' if opacity != 1 else ""
    return (
        f'<rect x="{x}" y="{y}" width="{max(0.0, w)}" height="{max(0.0, h)}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{width}"{extra}{fade}/>'
    )


def line(
    x1: float, y1: float, x2: float, y2: float, *, stroke: str, width: float = 1,
    dash: str = "",
) -> str:
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{stroke}" stroke-width="{width}"{extra}/>'
    )


def polyline(points: list[tuple[float, float]], *, stroke: str, width: float = 1) -> str:
    rendered = " ".join(f"{x},{y}" for x, y in points)
    return (
        f'<polyline points="{rendered}" fill="none" '
        f'stroke="{stroke}" stroke-width="{width}"/>'
    )


def text(content: str, x: float, y: float, *, size: int = 11, fill: str) -> str:
    """Raw text with no box. For plant markings only — never for data."""
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}">'
        f"{escape_text(content)}</text>"
    )
