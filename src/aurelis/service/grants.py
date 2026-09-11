"""Recording, revoking and reading data grants."""

from __future__ import annotations

import datetime as dt
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger
from aurelis.service.tables import DataGrant

__all__ = ["KNOWN_SOURCES", "Grants", "catalogue_for", "feed_for", "microstructure_for"]

KNOWN_SOURCES: tuple[str, ...] = ("coinbase",)
"""Vendors the service can fetch from. A fixture desk is ``fixture:<desk>``."""


class Grants:
    """The one place a standing fetch permission is written or withdrawn."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    def grant(
        self,
        session: Session,
        *,
        source: str,
        desk: str,
        instruments: tuple[str, ...],
        granted_by: str,
        reason: str,
        interval: str = "1h",
        bars: int = 400,
        at: dt.datetime | None = None,
    ) -> DataGrant:
        if source not in KNOWN_SOURCES and not source.startswith("fixture:"):
            raise IntegrityViolation(
                f"{source!r} is not a vendor the service can fetch from; known "
                f"sources are {list(KNOWN_SOURCES)} and fixture:<desk>"
            )
        if not instruments:
            raise IntegrityViolation("a grant names at least one instrument")
        moment = at or self._clock.now()
        ref = allocate_ref(session, RefKind.GRANT)
        row = DataGrant(
            grant_id=uuid7(),
            ref=ref,
            source=source,
            desk=desk,
            instruments=list(instruments),
            interval=interval,
            bars=bars,
            granted_by=granted_by,
            granted_at=moment,
            reason=reason,
        )
        session.add(row)
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.DATA_GRANTED,
            actor=Actor.OPERATOR,
            subject=ref,
            payload={
                "source": source,
                "desk": desk,
                "instruments": list(instruments),
                "interval": interval,
                "bars": bars,
                "granted_by": granted_by,
                "reason": reason[:300],
            },
            at=moment,
        )
        return row

    def revoke(
        self, session: Session, ref: str, *, by: str, at: dt.datetime | None = None
    ) -> DataGrant:
        moment = at or self._clock.now()
        row = session.execute(sa.select(DataGrant).where(DataGrant.ref == ref)).scalar_one_or_none()
        if row is None:
            raise IntegrityViolation(f"no data grant {ref}")
        if row.revoked_at is not None:
            raise IntegrityViolation(f"{ref} was already revoked at {row.revoked_at}")
        row.revoked_by = by
        row.revoked_at = moment
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.DATA_GRANT_REVOKED,
            actor=Actor.OPERATOR,
            subject=ref,
            payload={"revoked_by": by},
            at=moment,
        )
        return row

    @staticmethod
    def active(session: Session) -> list[DataGrant]:
        return list(
            session.execute(
                sa.select(DataGrant).where(DataGrant.revoked_at.is_(None)).order_by(DataGrant.ref)
            ).scalars()
        )

    @staticmethod
    def all(session: Session) -> list[DataGrant]:
        return list(session.execute(sa.select(DataGrant).order_by(DataGrant.ref)).scalars())


def catalogue_for(grant: DataGrant) -> Any:
    """The vendor's product catalogue, for the same source a grant names."""
    if grant.source == "coinbase":
        from aurelis.world.sources import CoinbaseProducts

        return CoinbaseProducts()
    raise IntegrityViolation(f"no catalogue for source {grant.source!r}")


def microstructure_for(grant: DataGrant) -> tuple[Any, Any]:
    """The book and trades feeds for the same source a grant names."""
    if grant.source == "coinbase":
        from aurelis.intel.microstructure import CoinbaseBook, CoinbaseTrades

        return CoinbaseBook(), CoinbaseTrades()
    raise IntegrityViolation(f"no microstructure feed for source {grant.source!r}")


def feed_for(grant: DataGrant, *, clock: Clock | None = None) -> Any:
    """The vendor adapter a grant names. Built here and nowhere else."""
    if grant.source == "coinbase":
        from aurelis.intel.live import CoinbaseCandles

        return CoinbaseCandles()
    if grant.source.startswith("fixture:"):
        from aurelis.intel.fixturefeed import FixtureFeed
        from aurelis.org.desks import Desk

        return FixtureFeed(Desk(grant.source.split(":", 1)[1]), clock=clock or SystemClock())
    raise IntegrityViolation(f"no feed for source {grant.source!r}")
