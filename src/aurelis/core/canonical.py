"""Canonical serialisation, and the hash built on it.

Every provenance claim in Aurelis reduces to "this hash was computed from that
content". That only holds if the same content always serialises the same way,
so this module fixes the encoding once:

* keys sorted,
* no insignificant whitespace,
* UTF-8, not escaped to ASCII,
* ``Decimal`` as its exact string, never through ``float``,
* ``datetime`` through :func:`aurelis.core.clock.isoformat`,
* ``float`` refused outright.

The last one is the unusual choice and it is deliberate. ``0.1 + 0.2`` does
not round-trip, platform ``repr`` has changed across releases, and a money or
metric value that hashes differently on two machines destroys the only
mechanism that makes a result citable. Callers pass ``Decimal`` or a string.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from aurelis.core.clock import isoformat

__all__ = ["canonical_bytes", "canonical_json", "sha256_of", "short_hash"]

_HASH_PREFIX_LEN = 12


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        # Exact decimal text. `str(Decimal("1.10"))` keeps the trailing zero,
        # which matters: two prices that differ only in scale are different
        # records and should hash differently.
        return {"__decimal__": str(value)}
    if isinstance(value, dt.datetime):
        return {"__datetime__": isoformat(value)}
    if isinstance(value, dt.date):
        return {"__date__": value.isoformat()}
    if isinstance(value, UUID):
        return {"__uuid__": str(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        # Sets have no order, so impose one rather than hashing insertion order.
        return {"__set__": sorted(canonical_json(item) for item in value)}
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    raise TypeError(
        f"{type(value).__name__} is not canonically serialisable. "
        "Add a rule here rather than converting at the call site, so every "
        "caller hashes it the same way."
    )


def _reject_floats(value: Any) -> None:
    """Walk the structure and refuse any float.

    ``json.dumps`` would happily encode one; the point is to fail loudly at
    the boundary instead of producing a hash that differs across machines.
    """
    if isinstance(value, float):
        raise TypeError(
            "float is not canonically serialisable: use Decimal (or a string) so the "
            "hash is identical on every machine. Binary floats do not round-trip."
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(key)
            _reject_floats(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _reject_floats(item)


def canonical_json(payload: Any) -> str:
    """Deterministic JSON text for ``payload``."""
    _reject_floats(payload)
    return json.dumps(
        payload,
        default=_default,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_bytes(payload: Any) -> bytes:
    return canonical_json(payload).encode("utf-8")


def sha256_of(payload: Any) -> str:
    """Hex SHA-256 of the canonical encoding.

    ``bytes`` hash their own content directly — an artifact's hash must be the
    hash of the file, not of a JSON wrapper around it.
    """
    if isinstance(payload, bytes):
        return hashlib.sha256(payload).hexdigest()
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def short_hash(digest: str) -> str:
    """First 12 hex characters, for display only.

    Never used for lookup or equality. Truncated hashes collide, and a UI
    convenience that leaks into an identity check is a real bug.
    """
    return digest[:_HASH_PREFIX_LEN]
