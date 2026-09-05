"""Have we tried this before?

The cheapest question in the company, and the one most often skipped. A
duplicate hypothesis caught here costs nothing; the same duplicate caught after
registration has already spent a slot in the family's error budget, and caught
after the run has spent compute to re-learn something the corpus already knew.

The search is **deterministic on purpose**. No model call, no embedding, no
similarity service — a lexical match over families and claim tokens, which
means the same hypothesis returns the same prior art on every machine, in
every test, forever. A fuzzy matcher would find more; it would also make "did
the company know this already?" depend on which model happened to answer, and
that is a bad property for a record that gates spending.

Two distinctions the result type insists on:

*Searched-and-found-nothing* is not the same as *nothing to search*. An empty
corpus returning "no prior art" reads identically to a full one returning the
same, and the two justify completely different decisions. :class:`PriorArtReport`
carries the corpus size so the difference is visible.

*Matched* is not *duplicate*. The report ranks and explains; whether a match
means "already answered, drop it" or "adjacent, worth citing" is a judgement,
and it belongs to the person screening, not to a token overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.memory.tables import CorpusTrial
from aurelis.research.tables import Hypothesis

__all__ = [
    "PriorArt",
    "PriorArtReport",
    "STOPWORDS",
    "family_distance",
    "search",
    "tokenise",
]

_WORD = re.compile(r"[a-z0-9]+")

_STOPWORD_TEXT = """
a an and are as at be been but by can do does for from has have if in into is
it its of on or over than that the their then there these this to under upon
was were when which while will with without
"""

STOPWORDS = frozenset(_STOPWORD_TEXT.split())
"""Dropped before matching.

Kept small and domain-blind. A stopword list that grew to include "momentum" or
"volatility" would quietly stop the search from finding the very families it
most needs to find.
"""

_STRONG_OVERLAP = 0.55
_WEAK_OVERLAP = 0.30


def tokenise(text: str) -> frozenset[str]:
    """Content words, lowercased. Deterministic and boring by design."""
    return frozenset(
        word
        for word in _WORD.findall(text.lower())
        if len(word) > 2 and word not in STOPWORDS
    )


def family_distance(left: str, right: str) -> int:
    """How many segments of the family path two claims share.

    Families are hierarchical — ``strategy.momentum.crypto`` — so a shared
    prefix is a real statement about subject matter rather than a coincidence
    of vocabulary. This is what lets the search surface a trial that used
    entirely different words for the same idea.
    """
    a = [part for part in left.split(".") if part]
    b = [part for part in right.split(".") if part]
    shared = 0
    for one, other in zip(a, b, strict=False):
        if one != other:
            break
        shared += 1
    return shared


@dataclass(frozen=True, slots=True)
class PriorArt:
    """One earlier attempt at something similar, and why it matched."""

    ref: str
    origin: str
    """``aurelis`` or the corpus this came from. A reader must be able to tell
    what this company established from what it inherited."""

    statement: str
    family: str
    verdict: str
    shared_family_depth: int
    overlap: float
    matched_terms: tuple[str, ...]

    @property
    def strength(self) -> str:
        """Close, adjacent or distant — and never "duplicate".

        Two routes to *close*, because two different things can establish that
        earlier work is about the same subject. A three-segment family match
        plus any shared content word is one: in a hierarchical taxonomy,
        ``info.derivatives.funding`` agreeing to three levels is a strong
        statement even when the wording is nothing alike. Heavy lexical overlap
        inside a two-segment family is the other.

        Neither says the question was already answered. That judgement belongs
        to whoever is screening, and the report exists to put the earlier work
        in front of them.
        """
        if self.shared_family_depth >= 3 and self.matched_terms:
            return "close"
        if self.shared_family_depth >= 2 and self.overlap >= _STRONG_OVERLAP:
            return "close"
        if self.shared_family_depth >= 1 or self.overlap >= _WEAK_OVERLAP:
            return "adjacent"
        return "distant"

    def describe(self) -> str:
        terms = ", ".join(self.matched_terms[:6]) or "family only"
        return (
            f"{self.ref} ({self.origin}, {self.verdict}) — {self.strength} "
            f"match on {terms}: {self.statement[:160]}"
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "origin": self.origin,
            "verdict": self.verdict,
            "family": self.family,
            "strength": self.strength,
            # A string, not a float: this payload becomes a hashed artifact,
            # and a binary float would hash differently on different machines.
            "overlap": f"{self.overlap:.4f}",
            "matched_terms": list(self.matched_terms[:8]),
            "statement": self.statement[:400],
        }


@dataclass(frozen=True, slots=True)
class PriorArtReport:
    """What the search looked at, and what it found.

    ``searched`` is not bookkeeping. "We found nothing" is only informative if
    there was something to find, and a report that cannot distinguish an empty
    index from a genuinely novel idea would let the company believe it had
    checked when it had not.
    """

    claim: str
    family: str
    matches: tuple[PriorArt, ...]
    searched: int
    corpora: tuple[str, ...]

    @property
    def novel(self) -> bool:
        """No close match — which is a claim about *this index*, not the world."""
        return not any(art.strength == "close" for art in self.matches)

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(art.ref for art in self.matches)

    def describe(self) -> str:
        if not self.searched:
            return (
                "no prior art could be checked: nothing is indexed, so novelty "
                "is unknown rather than established"
            )
        if not self.matches:
            return f"no prior art among {self.searched} indexed trials"
        head = f"{len(self.matches)} of {self.searched} indexed trials are related"
        return head + "\n" + "\n".join(f"  {art.describe()}" for art in self.matches)

    def as_payload(self) -> dict[str, object]:
        return {
            "claim": self.claim,
            "family": self.family,
            "searched": self.searched,
            "corpora": list(self.corpora),
            "novel_to_this_index": self.novel,
            "matches": [art.as_payload() for art in self.matches],
        }


def search(
    session: Session,
    *,
    claim: str,
    family: str,
    limit: int = 5,
    exclude_ref: str | None = None,
) -> PriorArtReport:
    """Find earlier work resembling this claim, across every corpus held.

    Searches the company's own hypotheses and every imported corpus together,
    because the question is "has anyone tried this?" and an answer that
    silently excluded inherited work would be the wrong answer in exactly the
    cases the import exists to cover.
    """
    wanted = tokenise(claim)
    candidates: list[PriorArt] = []
    corpora: set[str] = set()
    searched = 0

    for trial in session.execute(sa.select(CorpusTrial)).scalars():
        searched += 1
        corpora.add(trial.corpus)
        art = _score(
            ref=trial.ref,
            origin=trial.corpus,
            # The title AND the source's own evidence note. The note is where
            # the corpus says what it actually measured, so searching it finds
            # trials whose title never mentions the thing they tested.
            statement=f"{trial.title or trial.hypothesis}. {trial.evidence}",
            family=trial.family,
            verdict=trial.verdict,
            wanted=wanted,
            family_query=family,
        )
        if art is not None:
            candidates.append(art)

    own = sa.select(Hypothesis)
    if exclude_ref:
        own = own.where(Hypothesis.ref != exclude_ref)
    for hypothesis in session.execute(own).scalars():
        searched += 1
        corpora.add("aurelis")
        art = _score(
            ref=hypothesis.ref,
            origin="aurelis",
            statement=hypothesis.claim,
            family=hypothesis.family,
            verdict=hypothesis.state,
            wanted=wanted,
            family_query=family,
        )
        if art is not None:
            candidates.append(art)

    candidates.sort(key=lambda art: (-art.shared_family_depth, -art.overlap, art.ref))
    return PriorArtReport(
        claim=claim,
        family=family,
        matches=tuple(candidates[:limit]),
        searched=searched,
        corpora=tuple(sorted(corpora)),
    )


def _score(
    *,
    ref: str,
    origin: str,
    statement: str,
    family: str,
    verdict: str,
    wanted: frozenset[str],
    family_query: str,
) -> PriorArt | None:
    """Rank one candidate, or return ``None`` if it is unrelated.

    Overlap is measured against the *shorter* token set rather than the union.
    A one-line claim and a paragraph-long one describing the same idea should
    match; Jaccard would penalise the pair for the difference in length, which
    is a fact about writing style and not about subject matter.
    """
    theirs = tokenise(statement)
    depth = family_distance(family_query, family)
    if not theirs or not wanted:
        return None if depth < 1 else _art(ref, origin, statement, family, verdict, depth, 0.0, ())

    shared = wanted & theirs
    overlap = len(shared) / max(1, min(len(wanted), len(theirs)))
    if depth < 1 and overlap < _WEAK_OVERLAP:
        return None
    return _art(
        ref, origin, statement, family, verdict, depth, overlap, tuple(sorted(shared))
    )


def _art(
    ref: str,
    origin: str,
    statement: str,
    family: str,
    verdict: str,
    depth: int,
    overlap: float,
    terms: tuple[str, ...],
) -> PriorArt:
    return PriorArt(
        ref=ref,
        origin=origin,
        statement=statement,
        family=family,
        verdict=verdict,
        shared_family_depth=depth,
        overlap=overlap,
        matched_terms=terms,
    )
