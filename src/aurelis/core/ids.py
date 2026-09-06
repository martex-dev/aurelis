"""Identity: time-ordered UUID primary keys, plus human reference codes.

Two identifier schemes, because they serve different readers.

**UUIDs** are the primary keys. They are UUIDv7-shaped — 48 bits of Unix
milliseconds followed by randomness — so they sort by creation time. That is
not cosmetic: an append-heavy ledger with random keys scatters B-tree inserts
across the whole index, and time-ordered keys keep them at the hot end.

**Reference codes** are what people and agents say out loud: ``AG-0042``,
``MSN-0007``, ``HYP-1842``. Short, typeable, and monotonic per kind. They come
from a counter table, so they are only unique within one database — which is
correct, because they are a display and citation convenience, never a join key.

Python has no ``uuid7`` before 3.14, and Aurelis targets 3.12, so the
generator is written out here.
"""

from __future__ import annotations

import os
import time
import uuid
from enum import StrEnum

__all__ = ["RefKind", "format_ref", "parse_ref", "uuid7"]


def uuid7(*, now_ms: int | None = None) -> uuid.UUID:
    """A UUIDv7: millisecond timestamp, then 74 bits of randomness.

    Version and variant bits are set per RFC 9562, so these are valid UUIDs to
    anything else that reads them.
    """
    stamp = int(time.time() * 1000) if now_ms is None else now_ms
    if not 0 <= stamp < (1 << 48):
        raise ValueError(f"timestamp out of UUIDv7 range: {stamp}")

    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits, 74 of them survive
    value = stamp << 80 | rand
    value &= ~(0xF << 76)  # clear version nibble
    value |= 0x7 << 76  # version 7
    value &= ~(0x3 << 62)  # clear variant bits
    value |= 0x2 << 62  # RFC 9562 variant
    return uuid.UUID(int=value)


class RefKind(StrEnum):
    """Reference-code prefixes.

    A closed vocabulary. A new entity kind that people will cite by name gets
    a prefix here, so the set of things with a public name stays reviewable.
    """

    AGENT = "AG"
    TEAM = "TM"
    DESK = "DSK"
    MISSION = "MSN"
    PROJECT = "PRJ"
    TASK = "TSK"
    MESSAGE = "MSG"
    MEETING = "MTG"
    KICKOFF = "KCK"
    """The plan a mission starts from. Its own prefix rather than MTG-,
    because a kickoff RECORD and the MEETING that produced it are two
    different things and a shared numbering makes the ledger read as though
    twice as many meetings were held."""

    RETROSPECTIVE = "RTR"
    DECISION = "DEC"
    OBSERVATION = "OBS"
    HYPOTHESIS = "HYP"
    REGISTRATION = "REG"
    EXPERIMENT = "EXP"
    RUN = "RUN"
    FINDING = "FND"
    EVIDENCE = "EVD"
    OBJECTION = "OBJ"
    REPLICATION = "RPL"
    COMPONENT = "CMP"
    """An authored piece of a strategy. Its own prefix because components are
    reused across strategies and outlive any one of them."""

    STRATEGY = "STR"
    STRATEGY_VERSION = "SV"
    PORTFOLIO = "PTF"
    RISK_ASSESSMENT = "RSK"
    TRADE_PROPOSAL = "TPR"
    TRADE_APPROVAL = "TAP"
    ALLOCATION = "ALC"
    PROPOSAL = "PRP"
    ORDER = "ORD"
    ALERT = "ALT"
    LESSON = "LSN"
    AUDIT = "AUD"
    ORG_CHANGE = "ORG"
    TRAINING_RUN = "TRN"
    """One agent's pass over the training-scenario suite. Its own prefix
    because a scenario score is cited alongside live work and must never be
    mistaken for it (ADR-0005)."""

    @property
    def width(self) -> int:
        """Zero-padding width. Wide enough that codes stay sortable as text."""
        return 4


def format_ref(kind: RefKind, number: int) -> str:
    """``(RefKind.AGENT, 42) -> "AG-0042"``.

    Numbers past the padding width simply get longer; the code stays valid and
    stops being text-sortable, which is a cosmetic loss rather than a
    correctness one.
    """
    if number < 1:
        raise ValueError(f"reference numbers start at 1, got {number}")
    return f"{kind.value}-{number:0{kind.width}d}"


def parse_ref(ref: str) -> tuple[RefKind, int]:
    """Inverse of :func:`format_ref`. Raises ``ValueError`` on anything else."""
    prefix, _, digits = ref.partition("-")
    if not digits or not digits.isdigit():
        raise ValueError(f"not a reference code: {ref!r}")
    try:
        kind = RefKind(prefix)
    except ValueError:
        raise ValueError(f"unknown reference prefix {prefix!r} in {ref!r}") from None
    return kind, int(digits)
