"""Column types that refuse to lose information.

SQLite has no native datetime, no native decimal and no native UUID, and the
default round-trips silently degrade all three. Each type here fixes that at
the boundary so the rest of the system can hold the value it thinks it holds.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.engine import Dialect

from aurelis.core.clock import ensure_utc

__all__ = ["GUID", "Money", "UtcDateTime"]


class UtcDateTime(sa.TypeDecorator[dt.datetime]):
    """Timezone-aware UTC datetimes, enforced in both directions.

    SQLite drops the tzinfo on the way in and hands back a naive value on the
    way out. Storing naive and reattaching UTC on load would work until a
    caller wrote a non-UTC datetime, so this converts on the way in and
    refuses naive input rather than assuming.
    """

    impl = sa.DateTime
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        return ensure_utc(value).replace(tzinfo=None) if dialect.name == "sqlite" else ensure_utc(
            value
        )

    def process_result_value(self, value: dt.datetime | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else ensure_utc(value)


class Money(sa.TypeDecorator[Decimal]):
    """Exact decimal money, stored as text.

    Text rather than SQLite's REAL, because money through a binary float is
    how accounting drifts. Postgres would give a real NUMERIC, but keeping one
    representation means a database file copied between the two carries the
    same values.

    Scale is fixed at 8 places: model pricing is quoted per million tokens, so
    a single call routinely costs a fraction of a cent.
    """

    impl = sa.String(40)
    cache_ok = True

    _QUANTUM = Decimal("0.00000001")

    def process_bind_param(self, value: Decimal | int | str | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("money must not come from a float; pass Decimal or str")
        return str(Decimal(value).quantize(self._QUANTUM))

    def process_result_value(self, value: str | None, dialect: Dialect) -> Any:
        return None if value is None else Decimal(value)


class GUID(sa.TypeDecorator[uuid.UUID]):
    """UUID primary keys: native on Postgres, 32-char hex on SQLite.

    Hex without dashes so the stored form sorts identically to the UUIDv7
    byte order, which is the whole reason for using UUIDv7.
    """

    impl = sa.String(32)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PgUUID(as_uuid=True))
        return dialect.type_descriptor(sa.String(32))

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return parsed if dialect.name == "postgresql" else parsed.hex

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
