"""Exact tests the company's measures share. Deterministic, no floats."""

from __future__ import annotations

import math
from decimal import Decimal
from fractions import Fraction

__all__ = ["sign_test"]

_P = Decimal("0.0001")


def sign_test(hits: int, n: int) -> Decimal:
    """P(at least ``hits`` of ``n`` fair coin tosses land heads). Exact.

    Counts, not sizes: one episode that tripled weighs the same as one that
    rose a cent, so a record cannot be carried by a single outlier.
    """
    if n <= 0:
        return Decimal(1)
    tail = sum(math.comb(n, k) for k in range(max(hits, 0), n + 1))
    share = Fraction(tail, 2**n)
    return (Decimal(share.numerator) / Decimal(share.denominator)).quantize(_P)
