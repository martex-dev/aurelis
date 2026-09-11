"""Pixel primitives: avatars and progress bars that carry only what the record says.

The brief asks for a pixel-art research facility that is game-like without
being childish, and `CLAUDE.md` §34 forbids decoration that pretends to be
instrumentation. The two are reconciled by one rule: **a pixel is allowed to
carry identity or measured state, and nothing else.**

An avatar is identity. It is an eight-by-eight sprite, mirrored so it reads as
a face, drawn from the SHA-256 of the agent's reference — the same agent is
the same sprite on every page and every build, and no two agents collide by
accident more often than a hash does. It is coloured by the tone the caller
passes, which is the room's status colour, so a working agent's portrait is
lit and an idle one is not.

A progress bar is measured state. Its width is ``done / total`` and the two
numbers are printed beside it, because a bar without its numbers is a mood.
It never invents a total: a caller with nothing to measure gets no bar.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from aurelis.station.svg import escape_text

__all__ = ["avatar_svg", "progress_bar", "sprite_rows"]

_GRID = 8
_HALF = _GRID // 2


def sprite_rows(ref: str) -> tuple[tuple[bool, ...], ...]:
    """The lit pixels of a reference's sprite, eight rows of eight, mirrored.

    Bits come from the digest of the reference; the left half is drawn and
    the right half reflects it. The middle two rows are forced to have at
    least one lit pixel near the centre so every sprite has a face rather than
    two detached ears.
    """
    digest = hashlib.sha256(ref.encode("utf-8")).digest()
    rows: list[tuple[bool, ...]] = []
    for row in range(_GRID):
        byte = digest[row]
        half = [bool((byte >> bit) & 1) for bit in range(_HALF)]
        if row in (3, 4):
            half[_HALF - 1] = True
        rows.append(tuple(half + half[::-1]))
    return tuple(rows)


def avatar_svg(ref: str, *, tone: str, size: int = 32, title: str = "") -> str:
    """The sprite as inline SVG, ``size`` pixels square, crisp-edged."""
    cell = max(1, size // _GRID)
    label = escape_text(title or ref)
    cells = "".join(
        f'<rect x="{x * cell}" y="{y * cell}" width="{cell}" height="{cell}"/>'
        for y, row in enumerate(sprite_rows(ref))
        for x, lit in enumerate(row)
        if lit
    )
    return (
        f'<svg class="avatar" viewBox="0 0 {cell * _GRID} {cell * _GRID}" '
        f'width="{cell * _GRID}" height="{cell * _GRID}" role="img" '
        f'aria-label="{label}" shape-rendering="crispEdges" fill="{escape_text(tone)}">'
        f"<title>{label}</title>{cells}</svg>"
    )


def progress_bar(done: int, total: int, *, tone: str = "warn", label: str = "") -> str:
    """A bar whose width is ``done / total``, with the numbers printed beside it.

    Clamped to the bar: a ``done`` past ``total`` is drawn full and still
    printed as it is, so an over-achiever shows ``25/20``, not a lie. A
    non-positive ``total`` is nothing to measure and returns an empty string.
    """
    if total <= 0:
        return ""
    ratio = min(Decimal(max(done, 0)) / Decimal(total), Decimal(1))
    width = int((ratio * 100).to_integral_value())
    caption = escape_text(label or f"{done}/{total}")
    return (
        f'<span class="bar {escape_text(tone)}" title="{caption}">'
        f'<span class="fill" style="width:{width}%"></span></span>'
        f'<span class="bar-n">{caption}</span>'
    )
