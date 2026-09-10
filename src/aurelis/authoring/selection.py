"""What a search returns by luck, and what is left after subtracting it.

M15 declared how wide a search was. Declaring a width is only half of the job:
the number that comes out of the search still has to be corrected for it, or
the declaration is a footnote nobody applies.

The correction is the oldest result in the multiple-testing literature and it
is brutal. Search a space where **nothing** has an edge, take the best result,
and you do not get zero — you get the largest of *n* draws from the estimator's
own noise, which grows with *n*. So:

.. code-block:: text

    best observed Sharpe        what the campaign found
    expected best of n          what searching n times returns from noise alone
    the difference              what the search actually produced

A campaign whose best result is *below* the expected best of its own width has
produced nothing, and has produced it expensively.

Why this is computed here rather than called
--------------------------------------------

:mod:`aurelis.engines.martex` already wraps martex-quant's deflated Sharpe, and
that is the right thing to call when it is installed. It is an optional extra,
absent from the environment CI runs in, and a correction that silently does not
run in CI is a correction nobody applies. So the expected-best half is computed
here from the standard library, using the same Bailey–López de Prado
approximation martex's ``expected_max_sharpe`` uses, and the two agree by
construction rather than by coincidence.

What it assumes, plainly
------------------------

The draws are treated as independent and normal. Neither is true: 72 designs
over one price series are heavily correlated, and Sharpe estimates are skewed.
Correlation makes the true expected maximum **smaller** than this, so the
correction as computed is conservative — it may call a real edge nothing, and
will not call nothing an edge. That is the direction to be wrong in, and it is
stated on every report rather than left in a docstring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from statistics import NormalDist
from typing import Any

__all__ = [
    "EULER",
    "SelectionCheck",
    "check_selection",
    "expected_best_of",
    "standard_error_from",
]

EULER = 0.5772156649015329
"""The Euler–Mascheroni constant, from the expected-maximum approximation.

Kept as a named constant rather than inlined because it is the only magic
number in the file, and a reader should be able to find out what it is without
recognising it.
"""

_Z = 1.96
"""The multiplier the engine's Sharpe interval was built with.

Recovering the standard error from the interval means undoing exactly what
:meth:`~aurelis.engines.local.LocalEngine.sharpe_with_interval` did. If that
method ever changes its multiplier, this must change with it — which is why the
recovery lives in one function and not at three call sites.
"""


def expected_best_of(n: int, standard_error: Decimal) -> Decimal:
    """The best Sharpe a search of ``n`` designs returns from noise alone.

    Zero for a single trial: one draw has no maximum to inflate. Above that,
    the Bailey–López de Prado approximation to the expected maximum of ``n``
    standard normals, scaled by the estimator's own standard error.
    """
    if n < 1:
        raise ValueError("a search has at least one trial; the trial itself counts")
    if n == 1 or standard_error <= 0:
        return Decimal(0)
    normal = NormalDist()
    expected = (1 - EULER) * normal.inv_cdf(1 - 1 / n) + EULER * normal.inv_cdf(
        1 - 1 / (n * math.e)
    )
    return (standard_error * Decimal(str(expected))).quantize(Decimal("0.00000001"))


def standard_error_from(low: Decimal | None, high: Decimal | None) -> Decimal | None:
    """Recover the estimator's standard error from the interval it produced.

    ``None`` when the run reported no interval, and ``None`` is propagated
    rather than replaced by a guess: a correction computed from an assumed
    standard error would be a number with no measurement behind it, which is
    the one thing this company does not put on a report.
    """
    if low is None or high is None:
        return None
    width = high - low
    if width <= 0:
        return None
    return (width / (Decimal(2) * Decimal(str(_Z)))).quantize(Decimal("0.00000001"))


@dataclass(frozen=True, slots=True)
class SelectionCheck:
    """A best-of-n result, and what is left of it after the search is paid for."""

    observed: Decimal
    expected_by_chance: Decimal
    n_trials: int
    standard_error: Decimal | None

    @property
    def surplus(self) -> Decimal:
        """Observed minus what searching this wide returns from noise."""
        return self.observed - self.expected_by_chance

    @property
    def survives(self) -> bool:
        """Whether anything is left. Not a verdict — a subtraction.

        Deliberately not called ``passed``. Clearing the expected maximum is
        the *minimum* a searched result must do, not evidence that it works: a
        surplus this side of an interval is still one number.
        """
        return self.standard_error is not None and self.surplus > 0

    @property
    def measurable(self) -> bool:
        return self.standard_error is not None

    def describe(self) -> str:
        if not self.measurable:
            return (
                f"the best of {self.n_trials} measured {self.observed}, and the "
                "run reported no interval, so how much of it is search cannot "
                "be computed"
            )
        verb = "clears" if self.survives else "does NOT clear"
        return (
            f"the best of {self.n_trials} measured {self.observed} and {verb} "
            f"the {self.expected_by_chance} that searching {self.n_trials} "
            f"times returns from noise alone (surplus {self.surplus})"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "observed": str(self.observed),
            "expected_by_chance": str(self.expected_by_chance),
            "surplus": str(self.surplus),
            "n_trials": self.n_trials,
            "standard_error": (
                str(self.standard_error) if self.standard_error is not None else None
            ),
            "survives": self.survives,
            "assumption": (
                "Draws are treated as independent and normal. Designs over one "
                "price series are correlated, which makes the true expected "
                "maximum smaller than this — so the correction is conservative "
                "and may call a real edge nothing."
            ),
        }


def check_selection(
    *,
    observed: Decimal,
    low: Decimal | None,
    high: Decimal | None,
    n_trials: int,
) -> SelectionCheck:
    """Subtract the search from the result."""
    error = standard_error_from(low, high)
    return SelectionCheck(
        observed=observed,
        expected_by_chance=(
            expected_best_of(n_trials, error) if error is not None else Decimal(0)
        ),
        n_trials=n_trials,
        standard_error=error,
    )
