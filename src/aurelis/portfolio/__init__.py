"""The book: what the company would like to hold, before Risk decides.

Kept apart from ``risk`` because the two must be able to disagree, and apart
from signal generation because `CLAUDE.md` §11 requires it: individual
strategies do not control the portfolio, and the best strategy on its own is
not automatically the best component of a book.

The measured correlation lives here and gate C reads it. That is the mechanism
behind the claim — a version can pass every solo test and still add nothing to
a book it moves with, and this is where that is caught with a number rather
than an intuition.
"""

from aurelis.portfolio.construction import Book, Correlations, Exposure, correlation
from aurelis.portfolio.tables import Allocation, ExposureSnapshot, Portfolio

__all__ = [
    "Allocation",
    "Book",
    "Correlations",
    "Exposure",
    "ExposureSnapshot",
    "Portfolio",
    "correlation",
]
