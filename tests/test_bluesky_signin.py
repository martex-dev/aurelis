"""M49 — Bluesky reads in full with an app password a person supplies.

* with no account supplied, the search is anonymous, as before,
* with one, the reader opens one session through the official endpoint,
  searches signed in, and reuses the session,
* an expired session is renewed once and the search is tried again,
* the account is optional: the catalogue and ``aurelis source keys`` say so,
  and never show a value.

**Nothing here touches the network.**
"""

from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from typing import Any

import pytest

from aurelis.intel import social
from aurelis.intel.social import BlueskySearch
from aurelis.sources.catalogue import CATALOGUE, KEY_PREFIX, key_status

_HANDLE = f"{KEY_PREFIX}BLUESKY_HANDLE"
_PASSWORD = f"{KEY_PREFIX}BLUESKY_APP_PASSWORD"
_SECRET = "abcd-efgh-ijkl-mnop"

_POSTS = {
    "posts": [
        {
            "uri": "at://did:plc:x/app.bsky.feed.post/3k",
            "author": {"handle": "someone.bsky.social"},
            "record": {"text": "arbitrum is moving", "createdAt": "2026-09-25T12:00:00Z"},
            "likeCount": 3,
            "repostCount": 1,
        }
    ]
}


class _Bluesky:
    def __init__(self, *, expire_first: bool = False) -> None:
        self.requests: list[Any] = []
        self.sessions = 0
        self.expire_first = expire_first

    def __call__(self, request: Any, timeout: int = 0) -> Any:  # noqa: ARG002
        self.requests.append(request)
        if request.full_url.endswith("createSession"):
            self.sessions += 1
            return io.BytesIO(json.dumps({"accessJwt": f"token-{self.sessions}"}).encode())
        if self.expire_first and request.get_header("Authorization") == "Bearer token-1":
            raise urllib.error.HTTPError(request.full_url, 400, "ExpiredToken", Message(), None)
        return io.BytesIO(json.dumps(_POSTS).encode())


@pytest.fixture(autouse=True)
def _no_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(social, "_BLUESKY_SESSION", {})
    monkeypatch.delenv(_HANDLE, raising=False)
    monkeypatch.delenv(_PASSWORD, raising=False)


def test_with_no_account_supplied_the_search_is_anonymous() -> None:
    feed = _Bluesky()
    posts = BlueskySearch(CATALOGUE["bluesky"], opener=feed).posts("arbitrum")
    assert [p.text for p in posts] == ["arbitrum is moving"]
    (only,) = feed.requests
    assert only.full_url.startswith("https://api.bsky.app/") and not only.has_header(
        "Authorization"
    )


def test_with_an_account_the_reader_opens_one_session_and_searches_signed_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_HANDLE, "company.bsky.social")
    monkeypatch.setenv(_PASSWORD, _SECRET)
    feed = _Bluesky()
    reader = BlueskySearch(CATALOGUE["bluesky"], opener=feed)
    assert reader.posts("arbitrum") and reader.posts("avalanche")
    assert feed.sessions == 1, "one session for the life of the process"
    session, first, second = feed.requests
    assert json.loads(session.data) == {"identifier": "company.bsky.social", "password": _SECRET}
    assert first.full_url.startswith("https://bsky.social/xrpc/app.bsky.feed.searchPosts")
    assert first.get_header("Authorization") == "Bearer token-1"
    assert second.get_header("Authorization") == "Bearer token-1"


def test_an_expired_session_is_renewed_once_and_the_search_tried_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_HANDLE, "company.bsky.social")
    monkeypatch.setenv(_PASSWORD, _SECRET)
    feed = _Bluesky(expire_first=True)
    posts = BlueskySearch(CATALOGUE["bluesky"], opener=feed).posts("arbitrum")
    assert posts and feed.sessions == 2
    assert feed.requests[-1].get_header("Authorization") == "Bearer token-2"


def test_the_account_is_optional_and_its_value_is_never_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bluesky = CATALOGUE["bluesky"]
    assert bluesky.keyless and bluesky.available
    assert _HANDLE in bluesky.key and "reads more" in bluesky.key
    rows = [r for r in key_status() if r["source"] == "bluesky"]
    assert {(r["variable"], r["required"], r["set"]) for r in rows} == {
        (_HANDLE, "no", "no"),
        (_PASSWORD, "no", "no"),
    }
    monkeypatch.setenv(_HANDLE, "company.bsky.social")
    monkeypatch.setenv(_PASSWORD, _SECRET)
    assert "optional sign-in is supplied" in bluesky.key
    assert all(_SECRET not in str(r) for r in key_status())
