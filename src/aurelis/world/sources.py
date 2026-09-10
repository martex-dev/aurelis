"""The first non-price event source: a venue's own product catalogue.

Coinbase publishes its product list without credentials: every instrument,
its base and quote asset, and its status — online, offline, delisted,
trading disabled. Read on every wake and diffed against what the company
already holds, that is a stream of real events: a product seen for the first
time (a listing), a status change (a halt, a delisting), a product that
disappeared. Listing front-running and delisting flows are two of the
mechanisms the brief names, and this is the data they need.

Recorded exactly as bars are: the fetch is injectable, nothing in the test
suite reaches the network, and every event carries the endpoint it came from.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock
from aurelis.intel.live import USER_AGENT, FeedUnavailable
from aurelis.world.store import World

__all__ = ["CatalogueSync", "CoinbaseProducts", "sync_catalogue"]

_TRACKED: tuple[str, ...] = ("status", "trading_disabled", "cancel_only", "post_only", "limit_only")
"""Which product fields a change in is an event. A closed list, so the stream
does not fill with fields nobody reasons over."""


@dataclass(frozen=True, slots=True)
class CoinbaseProducts:
    """``GET /products`` on the public exchange API. No credentials."""

    name: str = "coinbase"
    endpoint: str = "https://api.exchange.coinbase.com/products"
    timeout: int = 25
    opener: Any = None

    def products(self) -> list[dict[str, Any]]:
        request = urllib.request.Request(self.endpoint, headers={"User-Agent": USER_AGENT})
        opener = self.opener or urllib.request.urlopen
        try:
            with opener(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise FeedUnavailable(f"{self.name} refused the catalogue ({error.code})") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise FeedUnavailable(f"{self.name} catalogue could not be reached: {error}") from error
        if not isinstance(payload, list):
            raise FeedUnavailable(f"{self.name} returned {type(payload).__name__}, not a list")
        return [row for row in payload if isinstance(row, dict) and "id" in row]


@dataclass(frozen=True, slots=True)
class CatalogueSync:
    """What one sync did."""

    seen: int
    new_listings: tuple[str, ...]
    status_changes: tuple[str, ...]
    disappeared: tuple[str, ...]

    def describe(self) -> str:
        return (
            f"{self.seen} product(s); {len(self.new_listings)} new, "
            f"{len(self.status_changes)} status change(s), {len(self.disappeared)} gone"
        )


def sync_catalogue(
    session: Session,
    world: World,
    feed: CoinbaseProducts,
    *,
    clock: Clock,
    at: dt.datetime | None = None,
) -> CatalogueSync:
    """Read the catalogue, update the entities, and record what changed as events.

    The first sync of a workspace records every product as ``listing.seen``.
    That is a fact about the company (it saw the catalogue for the first time)
    rather than about the market, and the event payload says so with
    ``first_sync: true`` so a later reader does not mistake a thousand initial
    sightings for a thousand listings on one day.
    """
    moment = at or clock.now()
    products = feed.products()
    venue_source = feed.endpoint
    world.see(session, kind="venue", key=feed.name, name=feed.name, source=venue_source, at=moment)
    first_sync = world.entity(session, "venue", feed.name) is not None and not any(
        True for _ in _known_instruments(session, feed.name)
    )

    known = {row.key: row for row in _known_instruments(session, feed.name)}
    new_listings: list[str] = []
    changes: list[str] = []
    seen_keys: set[str] = set()

    for product in products:
        key = str(product["id"])
        seen_keys.add(key)
        tracked = {field: product.get(field) for field in _TRACKED}
        attributes = {
            "base": product.get("base_currency"),
            "quote": product.get("quote_currency"),
            **tracked,
        }
        previous = known.get(key)
        # Read the old state before `see` updates the row: `previous` is the
        # same ORM object the identity map will hand back, so comparing after
        # the update compares the new state with itself. Found by the test.
        before = (
            None
            if previous is None
            else {field: previous.attributes.get(field) for field in _TRACKED}
        )
        entity, is_new = world.see(
            session,
            kind="instrument",
            key=key,
            name=str(product.get("display_name") or key),
            attributes=attributes,
            source=venue_source,
            at=moment,
        )
        base = product.get("base_currency")
        quote = product.get("quote_currency")
        if base:
            world.see(session, kind="asset", key=str(base), source=venue_source, at=moment)
            world.relate(
                session,
                subject=("instrument", key),
                kind="base_asset",
                obj=("asset", str(base)),
                source=venue_source,
                at=moment,
            )
        if quote:
            world.see(session, kind="asset", key=str(quote), source=venue_source, at=moment)
            world.relate(
                session,
                subject=("instrument", key),
                kind="quote_asset",
                obj=("asset", str(quote)),
                source=venue_source,
                at=moment,
            )
        world.relate(
            session,
            subject=("instrument", key),
            kind="listed_on",
            obj=("venue", feed.name),
            source=venue_source,
            at=moment,
        )
        if is_new:
            new_listings.append(key)
            world.record(
                session,
                kind="listing.seen",
                at=moment,
                entity_kind="instrument",
                entity_key=key,
                payload={**tracked, "first_sync": first_sync},
                source=venue_source,
                recorded_at=moment,
            )
            continue
        assert before is not None
        if before != tracked:
            changes.append(key)
            world.record(
                session,
                kind="listing.status_changed",
                at=moment,
                entity_kind="instrument",
                entity_key=key,
                payload={"before": before, "after": tracked},
                source=venue_source,
                recorded_at=moment,
            )

    disappeared = sorted(set(known) - seen_keys)
    for key in disappeared:
        world.record(
            session,
            kind="listing.gone",
            at=moment,
            entity_kind="instrument",
            entity_key=key,
            payload={"last_seen": known[key].attributes},
            source=venue_source,
            recorded_at=moment,
        )
    return CatalogueSync(
        seen=len(products),
        new_listings=tuple(new_listings),
        status_changes=tuple(changes),
        disappeared=tuple(disappeared),
    )


def _known_instruments(session: Session, venue: str) -> list[Any]:
    import sqlalchemy as sa

    from aurelis.world.tables import Entity, Relation

    return list(
        session.execute(
            sa.select(Entity)
            .join(
                Relation,
                sa.and_(
                    Relation.subject_kind == Entity.kind,
                    Relation.subject_key == Entity.key,
                    Relation.kind == "listed_on",
                    Relation.object_key == venue,
                ),
            )
            .where(Entity.kind == "instrument")
        ).scalars()
    )
