"""Core: identity, time, canonical encoding."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from aurelis.core.canonical import canonical_json, sha256_of, short_hash
from aurelis.core.clock import FrozenClock, SystemClock, ensure_utc, isoformat, parse_utc
from aurelis.core.ids import RefKind, format_ref, parse_ref, uuid7

# --------------------------------------------------------------------- clock


def test_system_clock_is_utc_aware() -> None:
    assert SystemClock().now().tzinfo is dt.UTC


def test_frozen_clock_does_not_move_on_its_own() -> None:
    clock = FrozenClock(dt.datetime(2026, 9, 4, tzinfo=dt.UTC))
    assert clock.now() == clock.now()


def test_frozen_clock_advances_only_when_told() -> None:
    clock = FrozenClock(dt.datetime(2026, 9, 4, tzinfo=dt.UTC))
    clock.advance(hours=3)
    assert clock.now() == dt.datetime(2026, 9, 4, 3, tzinfo=dt.UTC)


def test_naive_datetime_is_refused_not_assumed() -> None:
    """Assuming a zone is how every bar in a dataset silently shifts."""
    with pytest.raises(ValueError, match="naive datetime rejected"):
        ensure_utc(dt.datetime(2026, 9, 4))  # noqa: DTZ001


def test_non_utc_is_converted_not_rejected() -> None:
    eastern = dt.timezone(dt.timedelta(hours=-5))
    moment = dt.datetime(2026, 9, 4, 7, tzinfo=eastern)
    assert ensure_utc(moment) == dt.datetime(2026, 9, 4, 12, tzinfo=dt.UTC)


def test_isoformat_round_trips() -> None:
    moment = dt.datetime(2026, 9, 4, 9, 30, 15, 123456, tzinfo=dt.UTC)
    assert parse_utc(isoformat(moment)) == moment


def test_isoformat_is_stable_for_hashing() -> None:
    moment = dt.datetime(2026, 9, 4, tzinfo=dt.UTC)
    assert isoformat(moment) == "2026-09-04T00:00:00.000000Z"


# ----------------------------------------------------------------------- ids


def test_uuid7_is_version_7_and_rfc_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert (value.int >> 62) & 0x3 == 0x2


def test_uuid7_sorts_by_creation_time() -> None:
    """Time-ordered keys keep index inserts at the hot end of the B-tree."""
    early = uuid7(now_ms=1_700_000_000_000)
    late = uuid7(now_ms=1_800_000_000_000)
    assert early.hex < late.hex


def test_uuid7_values_are_distinct() -> None:
    same_ms = {uuid7(now_ms=1_700_000_000_000) for _ in range(500)}
    assert len(same_ms) == 500


def test_ref_formats_and_parses() -> None:
    assert format_ref(RefKind.AGENT, 42) == "AG-0042"
    assert parse_ref("AG-0042") == (RefKind.AGENT, 42)


def test_ref_codes_sort_as_text_within_the_padding_width() -> None:
    codes = [format_ref(RefKind.HYPOTHESIS, n) for n in (2, 10, 1842)]
    assert codes == sorted(codes)


def test_ref_numbers_start_at_one() -> None:
    with pytest.raises(ValueError, match="start at 1"):
        format_ref(RefKind.AGENT, 0)


def test_unknown_ref_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown reference prefix"):
        parse_ref("ZZZ-0001")


# ----------------------------------------------------------------- canonical


def test_key_order_does_not_change_the_hash() -> None:
    assert sha256_of({"a": 1, "b": 2}) == sha256_of({"b": 2, "a": 1})


def test_decimal_keeps_its_scale() -> None:
    """1.1 and 1.10 are different records and must hash differently."""
    assert sha256_of(Decimal("1.1")) != sha256_of(Decimal("1.10"))


def test_float_is_refused() -> None:
    """A binary float does not round-trip, so it must never enter a hash."""
    with pytest.raises(TypeError, match="float is not canonically serialisable"):
        canonical_json({"sharpe": 1.47})


def test_nested_float_is_refused_too() -> None:
    with pytest.raises(TypeError, match="float is not canonically serialisable"):
        canonical_json({"metrics": [{"value": 0.1}]})


def test_sets_hash_independently_of_insertion_order() -> None:
    assert sha256_of({"tags": {"a", "b"}}) == sha256_of({"tags": {"b", "a"}})


def test_bytes_hash_their_own_content() -> None:
    """An artifact's address must be the hash of the file, not of a wrapper."""
    import hashlib

    payload = b"experiment output"
    assert sha256_of(payload) == hashlib.sha256(payload).hexdigest()


def test_unserialisable_type_names_itself() -> None:
    class Custom:
        pass

    with pytest.raises(TypeError, match="Custom is not canonically serialisable"):
        canonical_json({"x": Custom()})


def test_short_hash_is_display_only() -> None:
    digest = sha256_of(b"x")
    assert short_hash(digest) == digest[:12]
    assert len(short_hash(digest)) == 12
