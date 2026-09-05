"""Every number on screen names where it came from.

This is the smallest module in the station and the one the whole thing rests
on. :class:`Figure` is a frozen dataclass whose second field is required, so
``Figure(4)`` is a ``TypeError`` — there is no way to put a number on a page
without saying which row, artifact or run it was read from. A test asserts
that, because the property is only worth anything if it cannot be worked
around.

The reason it is a type rather than a convention: a dashboard's failure mode is
not lying, it is *drifting*. Somebody hardcodes a plausible number during
layout work, the layout ships, and two months later nobody can tell which
figures on the page are real. Making the source mandatory means the drift
cannot start.

Three distinctions the type insists on.

**Zero is a number.** A department that held no meetings shows ``0``, drawn at
its true size. Rule 1 of the station is that every exit from every pipeline is
drawn even when it reads zero, because a pipeline that only shows its
successful branches is a sales diagram.

**Absent is not zero.** :meth:`Figure.absent` renders ``NO DATA`` and says
why. A strategy count of zero when no strategy table exists yet would be a
fabricated fact about an empty world; the honest statement is that nothing was
measured. The two look identical on a normal dashboard and justify completely
different conclusions.

**Derived is not measured.** :meth:`Figure.derived` marks a figure the station
computed by arithmetic over other figures — a sum, a percentage — and carries
the sources it came from. The station computes no *verdicts*; a count of rows
is not a conclusion, but a reader still has to be able to tell one from a
number the company itself recorded.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

__all__ = ["Figure", "Source", "SourceKind"]


class SourceKind(StrEnum):
    """Where a figure was read from.

    A closed vocabulary, because the set of things the station is allowed to
    cite should be reviewable. Adding a kind here is how a new backing store
    becomes citable.
    """

    TABLE = "table"
    """A row or an aggregate over a table in the workspace database."""

    LEDGER = "ledger"
    """The append-only event chain. The most citable thing in the system."""

    ARTIFACT = "artifact"
    """Content-addressed bytes. Cites a digest, so it cannot drift."""

    REGISTRY = "registry"
    """The compiled-in org registries: departments, desks, charters. Code, and
    therefore versioned by the commit rather than by a row."""

    DERIVED = "derived"
    """Arithmetic the station did over other figures, each of which is cited."""

    ABSENT = "absent"
    """Nothing was measured. Never rendered as a number."""


@dataclass(frozen=True, slots=True)
class Source:
    """What a figure was read from, precisely enough to go and look."""

    kind: SourceKind
    ref: str
    """The table name, event kind, artifact digest or registry name."""

    detail: str = ""
    """How it was obtained — the filter, the aggregate, the reason it is
    absent. This is what a reader needs when the number surprises them."""

    href: str = ""
    """Where clicking it goes, when the station has a page for it."""

    def describe(self) -> str:
        base = f"{self.kind.value}:{self.ref}"
        return f"{base} — {self.detail}" if self.detail else base

    @classmethod
    def table(cls, name: str, detail: str = "", href: str = "") -> Source:
        return cls(SourceKind.TABLE, name, detail, href)

    @classmethod
    def ledger(cls, detail: str = "", href: str = "/timeline") -> Source:
        return cls(SourceKind.LEDGER, "events", detail, href)

    @classmethod
    def artifact(cls, digest: str, detail: str = "") -> Source:
        return cls(SourceKind.ARTIFACT, digest, detail, f"/artifact/{digest}")

    @classmethod
    def registry(cls, name: str, detail: str = "") -> Source:
        return cls(SourceKind.REGISTRY, name, detail)


@dataclass(frozen=True, slots=True)
class Figure:
    """A value and the place it came from. Neither is optional.

    ``source`` has no default. That is the entire mechanism: a figure cannot be
    constructed without one, so a number cannot reach a template without a
    citation, so "nothing on this page was typed" is checkable by reading the
    type rather than by auditing every call site.
    """

    value: int | Decimal | str | None
    source: Source
    unit: str = ""
    from_sources: tuple[Source, ...] = field(default_factory=tuple)
    """For derived figures, everything the arithmetic read."""

    reason: str = ""
    """Why the value is absent. Empty for a figure that has one."""

    @classmethod
    def absent(cls, reason: str, *, unit: str = "") -> Figure:
        """Nothing was measured — and the page will say so.

        Distinct from a zero. A zero is a measurement; this is the absence of
        one, and rendering it as ``0`` would be inventing a fact about a world
        nobody looked at.
        """
        return cls(
            value=None,
            source=Source(SourceKind.ABSENT, "none", reason),
            unit=unit,
            reason=reason,
        )

    @classmethod
    def derived(
        cls,
        value: int | Decimal | str,
        *,
        how: str,
        sources: Sequence[Source],
        unit: str = "",
    ) -> Figure:
        """Arithmetic the station did, carrying what it read.

        Used for sums and percentages only. The station derives no verdicts —
        a verdict computed here would be a second, unversioned source of truth
        competing with the record.
        """
        if not sources:
            raise ValueError(
                "a derived figure must cite what it was derived from; one that "
                "does not is indistinguishable from a number somebody typed"
            )
        return cls(
            value=value,
            source=Source(SourceKind.DERIVED, "station", how),
            unit=unit,
            from_sources=tuple(sources),
        )

    @property
    def present(self) -> bool:
        return self.value is not None

    def render(self) -> str:
        """The text that goes on the page."""
        if self.value is None:
            return "NO DATA"
        text = _plain(self.value) if isinstance(self.value, Decimal) else str(self.value)
        return f"{text} {self.unit}".strip()

    def title(self) -> str:
        """The hover text: the citation, in full."""
        if self.value is None:
            return f"no data — {self.reason}"
        if self.from_sources:
            reads = "; ".join(source.describe() for source in self.from_sources)
            return f"{self.source.describe()} over {reads}"
        return self.source.describe()


def _plain(value: Decimal) -> str:
    """A decimal as it was declared, not as the money column padded it.

    The money type fixes the scale at eight places. Printing ``0.11000000``
    where somebody wrote ``0.11`` makes a threshold look like a computed
    result, so the padding comes off on the way to the screen.
    """
    text = format(value.normalize(), "f")
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".") or "0"
