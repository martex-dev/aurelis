"""Aurelis — an autonomous quantitative research corporation.

Ten departments, seven market desks, and a record that cannot be quietly
edited. See ``docs/`` for the architecture; ``CLAUDE.md`` for the charter.

Layering, strictly downward:

    station · cli
        v
    missions · meetings · comms
        v
    org · agents · research · strategy · portfolio · risk · trading · intel
        v
    skills · engines · governance · memory
        v
    platform · core

M0 ships the bottom two layers and the CLI that proves they work.

Schema changes are applied with ``create_all`` until the schema first has
to *change* under a live workspace, at which point Alembic arrives with a
real baseline. A migration tool with one revision and no history is
ceremony, and an empty ``migrations/`` directory would be a claim the
repository could not back up.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
