"""Following and dropping handles, and the list the wake reads."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.enums import EventKind
from aurelis.core.ids import RefKind, uuid7
from aurelis.platform.db.refs import allocate_ref
from aurelis.social.tables import SocialTarget

__all__ = [
    "PLATFORMS",
    "TOKEN_LINK",
    "Target",
    "active_targets",
    "drop_target",
    "follow_target",
    "normalise_handle",
]

PLATFORMS: tuple[str, ...] = ("telegram", "x", "discord")

TOKEN_LINK = "token link"
"""The origin of a target read off a followed token's own published links."""

_TELEGRAM = re.compile(r"^[a-z][a-z0-9_]{3,31}$")
_X = re.compile(r"^[a-z0-9_]{1,15}$")
_DISCORD = re.compile(r"^\d{5,25}/\d{5,25}$")

_NOT_A_CHANNEL = frozenset({"joinchat", "addstickers", "share", "proxy", "s", "c", "iv"})


class NotAHandle(ValueError):
    """The text is not a handle the platform could have."""


def normalise_handle(platform: str, raw: str) -> str:
    """One canonical spelling per handle: lower case, no URL, no ``@``.

    Telegram and X handles are case-insensitive, so ``@WhaleAlert`` and
    ``https://t.me/whalealert`` are one follow, not two. A Discord target is
    ``<server id>/<channel id>`` from the channel's URL.
    """
    text = raw.strip()
    if platform == "telegram":
        text = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/(s/)?", "", text, flags=re.I)
        handle = text.lstrip("@").split("/")[0].split("?")[0].lower()
        if handle in _NOT_A_CHANNEL or not _TELEGRAM.match(handle):
            raise NotAHandle(f"not a public Telegram channel name: {raw!r}")
        return handle
    if platform == "x":
        text = re.sub(r"^(https?://)?(www\.|mobile\.)?(x|twitter)\.com/", "", text, flags=re.I)
        handle = text.lstrip("@").split("/")[0].split("?")[0].lower()
        if handle in {"home", "search", "i", "intent", "share"} or not _X.match(handle):
            raise NotAHandle(f"not an X account name: {raw!r}")
        return handle
    if platform == "discord":
        text = re.sub(r"^(https?://)?(www\.|ptb\.|canary\.)?discord(app)?\.com/channels/", "", text)
        handle = "/".join(text.strip("/").split("/")[:2])
        if not _DISCORD.match(handle):
            raise NotAHandle(
                f"not a Discord channel: {raw!r}; copy the channel's link, which looks like "
                "https://discord.com/channels/<server>/<channel>"
            )
        return handle
    raise NotAHandle(f"no platform {platform!r}; one of {list(PLATFORMS)}")


@dataclass(frozen=True, slots=True)
class Target:
    platform: str
    handle: str
    on: str | None
    """The instrument every post lands on, or ``None`` to match by text."""

    origin: str
    reason: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.platform, self.handle)


def _decide(
    session: Session,
    *,
    platform: str,
    handle: str,
    followed: bool,
    reason: str,
    decided_by: str,
    on: str | None,
    at: dt.datetime,
    ledger: Any,
) -> SocialTarget:
    canonical = normalise_handle(platform, handle)
    if len(reason.strip()) < 8:
        raise ValueError("a follow or a drop needs a reason of at least a few words")
    row = SocialTarget(
        target_id=uuid7(),
        ref=allocate_ref(session, RefKind.SOCIAL_TARGET),
        platform=platform,
        handle=canonical,
        on_instrument=on,
        followed=followed,
        reason=reason.strip()[:600],
        decided_by=decided_by,
        decided_at=at,
    )
    session.add(row)
    session.flush()
    if ledger is not None:
        ledger.append(
            session,
            kind=EventKind.SOCIAL_FOLLOWED if followed else EventKind.SOCIAL_DROPPED,
            actor=decided_by,
            subject=row.ref,
            payload={
                "platform": platform,
                "handle": canonical,
                "on": on,
                "because": row.reason[:300],
            },
            at=at,
        )
    return row


def follow_target(
    session: Session,
    *,
    platform: str,
    handle: str,
    reason: str,
    decided_by: str,
    at: dt.datetime,
    on: str | None = None,
    ledger: Any = None,
) -> SocialTarget:
    """Start reading a handle. Recorded, with who decided it and why."""
    return _decide(
        session,
        platform=platform,
        handle=handle,
        followed=True,
        reason=reason,
        decided_by=decided_by,
        on=on,
        at=at,
        ledger=ledger,
    )


def drop_target(
    session: Session,
    *,
    platform: str,
    handle: str,
    reason: str,
    decided_by: str,
    at: dt.datetime,
    ledger: Any = None,
) -> SocialTarget:
    """Stop reading a handle. A drop also overrides a token's own link."""
    return _decide(
        session,
        platform=platform,
        handle=handle,
        followed=False,
        reason=reason,
        decided_by=decided_by,
        on=None,
        at=at,
        ledger=ledger,
    )


def _token_links(session: Session, tokens: tuple[str, ...]) -> list[Target]:
    """The X accounts and Telegram channels followed tokens publish."""
    if not tokens:
        return []
    from aurelis.world.tables import Entity

    rows = session.execute(
        sa.select(Entity.key, Entity.name, Entity.attributes).where(
            Entity.kind == "instrument", Entity.key.in_(tokens)
        )
    ).all()
    out: list[Target] = []
    for key, name, attributes in rows:
        links = (attributes or {}).get("links") or {}
        for platform in ("telegram", "x"):
            url = links.get(platform)
            if not url:
                continue
            try:
                handle = normalise_handle(platform, str(url))
            except NotAHandle:
                continue
            out.append(
                Target(
                    platform,
                    handle,
                    key,
                    TOKEN_LINK,
                    f"the {platform} link {name or key} publishes on DEX Screener",
                )
            )
    return out


def active_targets(
    session: Session,
    *,
    platform: str | None = None,
    tokens: tuple[str, ...] | list[str] = (),
) -> list[Target]:
    """What the wake reads: explicit follows, and the followed tokens' links.

    The newest decision on a handle wins. A handle someone dropped stays
    dropped even if a token links to it: the drop is a judgement about the
    handle, and a token cannot overrule it by linking.
    """
    query = sa.select(SocialTarget).order_by(
        SocialTarget.decided_at.desc(), SocialTarget.ref.desc()
    )
    if platform is not None:
        query = query.where(SocialTarget.platform == platform)
    latest: dict[tuple[str, str], SocialTarget] = {}
    for row in session.execute(query).scalars():
        latest.setdefault((row.platform, row.handle), row)
    chosen: dict[tuple[str, str], Target] = {
        key: Target(row.platform, row.handle, row.on_instrument, row.decided_by, row.reason)
        for key, row in latest.items()
        if row.followed
    }
    for target in _token_links(session, tuple(tokens)):
        if platform is not None and target.platform != platform:
            continue
        if target.key in latest:
            continue
        chosen.setdefault(target.key, target)
    return sorted(chosen.values(), key=lambda t: (t.platform, t.origin != TOKEN_LINK, t.handle))
