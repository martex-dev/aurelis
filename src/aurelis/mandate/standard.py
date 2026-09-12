"""What the company must be able to show before it asks to trade real money.

This is the milestone the whole project points at, and the shape of it was
specified by the person who has to act on it: the company does **not** get a
live adapter switched on for it. It reaches the judgement itself, on evidence,
and asks.

So the question is what would entitle it to ask. Twelve conditions, and every one
is checked against a row the company already writes — no self-assessment, no
prose, no confidence.

Why the standard is code
------------------------

It could have been a table, written once and frozen by a trigger. It is a
tuple, versioned with the source, because **the failure to defend against is
not editing the standard — it is editing it quietly.** A row frozen by a
trigger can be dropped and rewritten by anyone with the database; a tuple
changes the digest that every assessment records, and the change shows up in a
diff and in the history.

:func:`digest` is that hash. Every assessment stores it, and
:mod:`aurelis.mandate.assessment` reports when the standard has moved between
assessments — because a bar that was lowered after it was missed is the one
thing that would make all of this worthless.

Why it is this demanding
------------------------

A standard the current evidence passes would be a standard written to pass.
Every campaign this company has run ends with a negative surplus; no desk has
ever seen a market. The honest first answer is **not yet**, with the specific
numbers it is short by, and the standard has to be able to keep saying that
indefinitely.

It is demanding, not unreachable. Each condition names machinery that exists
and has run: authoring (M15), the selection correction (M16), replication (M5),
review (M14), risk (M8), paper trading and the gap measurement (M9), the
hash-chained ledger (M1). What is missing is a live feed, and the standard says
so first rather than last.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.canonical import sha256_of

__all__ = ["Criterion", "STANDARD", "digest", "as_payload"]


@dataclass(frozen=True, slots=True)
class Criterion:
    """One thing the company must be able to show, and how it is checked."""

    key: str
    asks: str
    why: str
    check: Callable[[Session], tuple[bool, str]]
    """Returns whether it is met and the reading that says so. The reading is
    returned either way: an unmet criterion that could not say what it found
    would be an assertion rather than a measurement."""

    blocked_by: str = ""
    """Why no amount of research could satisfy this today, if that is the case.

    The distinction between *unmet* and *unmeetable* is the difference between
    a result and a to-do list. Two criteria are blocked as this is written: no
    desk has a wired data feed, and nothing in the company writes a replication
    record -- the table exists and no code path fills it. Saying so is how the
    standard tells the company what to build rather than only what it lacks.
    """

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_by)

    def as_payload(self) -> dict[str, str]:
        return {
            "key": self.key,
            "asks": self.asks,
            "why": self.why,
            "blocked_by": self.blocked_by,
        }


# --------------------------------------------------------------- the checks


def _live_data(session: Session) -> tuple[bool, str]:
    """Has a real market ever entered the record?

    Checked against ingested snapshots rather than a flag on the desk. A
    snapshot is a hashed recording of bars that genuinely traded; a boolean on
    an opening is whatever the code that wrote it believed. The criterion is
    about the data, so it reads the data.
    """
    rows = session.execute(
        sa.text(
            "SELECT ref, source, symbol, bars, digest, fetched_at "
            "FROM market_snapshots WHERE is_live = 1 "
            "ORDER BY fetched_at DESC LIMIT 1"
        )
    ).all()
    if not rows:
        desks = session.execute(sa.text("SELECT count(*) FROM desk_openings")).scalar_one()
        return False, (
            f"no live market snapshot has been ingested; {desks} desk(s) opened, "
            "every one on a fixture"
        )
    ref, source, symbol, bars, dgst, fetched = rows[0]
    total = session.execute(
        sa.text("SELECT count(*) FROM market_snapshots WHERE is_live = 1")
    ).scalar_one()
    return True, (
        f"{total} live snapshot(s); newest {ref} — {bars} bar(s) of {symbol} "
        f"from {source}, digest {str(dgst)[:12]}, fetched {fetched}"
    )


MIN_SCORED_THESES = 30
"""How many scored, market-data theses a track record needs before it counts.

Thirty is where a mean Brier score stops being a handful of coin flips and
starts being a record; it is not where a sceptic goes quiet. The condition is
a floor on evidence, and the reading always carries the count so that "met"
can never be read as "enough".
"""


def _calibrated(session: Session) -> tuple[bool, str]:
    """Has the company built a forward track record that beats a coin toss?

    Read from sealed theses on **market** recordings only. A thesis about a
    fixture is a thesis about a random walk, and being calibrated on one is
    being calibrated on nothing. Pending theses are reported but do not count:
    a view is evidence once the outcome exists, not before.
    """
    from aurelis.judgement.calibration import COIN_TOSS, calibration_over
    from aurelis.judgement.tables import Thesis

    rows = list(
        session.execute(sa.select(Thesis).where(Thesis.is_live.is_(True))).scalars()
    )
    fixture = session.execute(
        sa.select(sa.func.count()).select_from(Thesis).where(Thesis.is_live.is_(False))
    ).scalar_one()
    record = calibration_over("company", rows)
    aside = f"; {fixture} more on fixtures, not counted" if fixture else ""
    if not record.scored:
        return False, (
            f"{record.sealed} view(s) sealed on market data, none scored yet"
            f"{aside}. A forward record needs at least {MIN_SCORED_THESES} scored"
        )
    met = record.scored >= MIN_SCORED_THESES and record.informative
    return met, (
        f"{record.scored} scored of {record.sealed} sealed on market data, "
        f"mean Brier {record.mean_brier} (coin toss {COIN_TOSS}, base rate "
        f"{record.base_rate_brier}), right {record.hit_rate}{aside}"
        + ("" if record.scored >= MIN_SCORED_THESES else f"; needs {MIN_SCORED_THESES} scored")
        + ("" if record.informative else "; no better than a coin toss")
    )


def _sourced(session: Session) -> tuple[bool, str]:
    """Do its analysts choose what the company reads, and is it read?

    Two halves, and the reading says which is missing: an analyst's request
    for a source from the free catalogue, which the loop can produce, and a
    news grant under which the service reads it, which only a person can.
    """
    from aurelis.service.grants import Grants
    from aurelis.sources.seat import active_sources

    wanted = active_sources(session)
    grants = [g for g in Grants.active(session) if g.is_news]
    if not wanted:
        return False, "no analyst has asked for a source from the free catalogue"
    if not grants:
        return False, (
            f"analysts asked for {', '.join(wanted)}; no news grant is recorded, and "
            "recording one is a person's decision"
        )
    return True, f"reads {', '.join(wanted)} under {', '.join(g.ref for g in grants)}"


def _scheme(session: Session) -> tuple[bool, str]:
    """Has a mechanism the agents stated beaten the base rate out of sample?

    Read from the mechanism record: predictions sealed as the trigger fired,
    the training occurrence excluded, scored against recordings, compared with
    the instrument's own unconditional drift. A mechanism nobody stated, or one
    still gathering, is reported as such rather than as a zero.
    """
    from aurelis.mechanism.library import Mechanisms

    statuses = Mechanisms().statuses(session)
    if not statuses:
        return False, "no mechanism has been stated over the event stream"
    schemes = [s for s in statuses if s.is_scheme]
    retired = sum(1 for s in statuses if s.retired)
    gathering = sum(1 for s in statuses if not s.retired and not s.enough)
    best = max(
        (s for s in statuses if s.calibration.mean_brier is not None),
        key=lambda s: -(s.calibration.mean_brier or 0),
        default=None,
    )
    reading = (
        f"{len(statuses)} mechanism(s): {len(schemes)} candidate scheme(s), "
        f"{gathering} gathering, {retired} retired"
    )
    if best is not None and best.calibration.mean_brier is not None:
        reading += (
            f"; best Brier {best.calibration.mean_brier} against base rate "
            f"{best.base_rate_brier} on {best.scored} scored"
        )
    return bool(schemes), reading


def _authored(session: Session) -> tuple[bool, str]:
    count = session.execute(
        sa.text("SELECT count(*) FROM authoring_attempts")
    ).scalar_one()
    return bool(count), f"{count} rule(s) written by an agent"


def _survived_selection(session: Session) -> tuple[bool, str]:
    rows = session.execute(
        sa.text(
            "SELECT ref, surplus, survives_selection FROM authoring_campaigns "
            "WHERE finished_at IS NOT NULL"
        )
    ).all()
    if not rows:
        return False, "no campaign has finished"
    survived = [str(ref) for ref, _, ok in rows if ok]
    best = max((str(s or "0") for _, s, _ in rows), key=lambda v: float(v))
    return (
        bool(survived),
        f"{len(survived)} of {len(rows)} campaign(s) cleared what a search "
        f"that wide returns from noise; best surplus {best}",
    )


def _beat_the_baselines(session: Session) -> tuple[bool, str]:
    total, beat = session.execute(
        sa.text(
            "SELECT count(*), coalesce(sum(CASE WHEN beat_baselines THEN 1 ELSE 0 END), 0) "
            "FROM authoring_attempts"
        )
    ).one()
    return (
        bool(beat),
        f"{beat} of {total} attempt(s) returned more than holding the asset",
    )


def _settled(session: Session) -> tuple[bool, str]:
    rows = session.execute(
        sa.text(
            "SELECT state, count(*) FROM hypotheses WHERE family LIKE 'authored.%' "
            "GROUP BY state"
        )
    ).all()
    counts = {str(state): int(n) for state, n in rows}
    confirmed = counts.get("confirmed", 0)
    return (
        bool(confirmed),
        f"authored claims by state: {counts or 'none'}"
        + ("" if confirmed else "; nothing has been confirmed"),
    )


def _replicated(session: Session) -> tuple[bool, str]:
    # "held" is the value aurelis.memory.confidence already counts. A second
    # spelling here would silently read zero forever.
    rows = session.execute(
        sa.text("SELECT outcome, count(*) FROM replications GROUP BY outcome")
    ).all()
    counts = {str(outcome): int(n) for outcome, n in rows}
    return bool(counts.get("held", 0)), (
        f"replications by outcome: {counts}"
        if counts
        else "no replication has ever been recorded"
    )


def _reviewed(session: Session) -> tuple[bool, str]:
    """A critic attacked something, and nothing it raised is still open.

    The first version of this required **no upheld objection anywhere**, and
    running it against a fully exercised company showed what that means: the
    M5 review ends with a critic correctly killing a survivorship-biased claim,
    so the criterion read unmet *because the company's critic had worked*. A
    bar that a healthy company can never clear is not a bar, it is a bug.

    Upheld and rejected are both settled -- the test ran and said so, and the
    thing an upheld objection killed is already refuted. What disqualifies is
    an objection nobody resolved. ``untestable`` is reported rather than
    blocking: no test could settle it within budget, which is a limitation to
    read, not an accusation left standing.
    """
    rows = session.execute(
        sa.text("SELECT status, count(*) FROM meeting_objections GROUP BY status")
    ).all()
    counts = {str(status): int(n) for status, n in rows}
    considered = sum(counts.values())
    if not considered:
        return False, "no objection has ever been raised against anything"
    still_open = counts.get("open", 0)
    return (
        still_open == 0,
        f"{considered} objection(s) raised: "
        + ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
        + ("; an objection nobody settled is one still standing" if still_open else ""),
    )


def _risk_cleared(session: Session) -> tuple[bool, str]:
    assessments = session.execute(
        sa.text("SELECT count(*) FROM risk_assessments")
    ).scalar_one()
    latched = session.execute(
        sa.text("SELECT count(*) FROM kill_latches WHERE cleared_at IS NULL")
    ).scalar_one()
    return (
        bool(assessments) and not latched,
        f"{assessments} risk assessment(s); {latched} kill latch(es) still set",
    )


def _paper_gap(session: Session) -> tuple[bool, str]:
    rows = session.execute(
        sa.text("SELECT metric, gap FROM gap_measurements")
    ).all()
    if not rows:
        return False, "paper trading has never been compared against a backtest"
    return True, f"{len(rows)} gap measurement(s): " + ", ".join(
        f"{metric} {gap}" for metric, gap in rows[:3]
    )


def _chain_intact(session: Session) -> tuple[bool, str]:
    from aurelis.platform.clock_default import default_clock
    from aurelis.platform.ledger.ledger import Ledger

    report = Ledger(default_clock()).verify(session)
    return report.ok, report.describe()


# ------------------------------------------------------------- the standard

STANDARD: tuple[Criterion, ...] = (
    Criterion(
        "live_data",
        "Has this company ever seen a real market?",
        "Every number it holds was computed on a fixture. A recommendation "
        "drawn from synthetic prices is a recommendation about the fixture.",
        _live_data,
    ),
    Criterion(
        "calibrated",
        "Have its agents built a forward track record — views sealed before "
        "the outcome, scored after it, better than a coin toss?",
        "A judgement cannot be backtested: a model asked about last year "
        "already knows what happened. The only honest evidence of skill is "
        "views stated in advance, sealed, and scored when the horizon expires.",
        _calibrated,
    ),
    Criterion(
        "scheme",
        "Has a mechanism the agents stated beaten the base rate out of sample?",
        "A mined pattern is a coincidence until an agent says why it works and "
        "the additional predictions it implies come true. The only evidence that "
        "the company found something is a mechanism whose sealed, out-of-sample "
        "predictions beat knowing only the drift.",
        _scheme,
    ),
    Criterion(
        "sourced",
        "Do its analysts choose what the company reads, and is it read?",
        "A source nobody asked for is noise the judges have to wade through; a "
        "source an analyst asked for, with a reason, and the service reads under "
        "a grant a person recorded, is the company deciding what it needs to know.",
        _sourced,
    ),
    Criterion(
        "authored",
        "Did an agent write the strategy, rather than a menu or the corpus supplying it?",
        "The company exists to create an edge, not to sift for one. A strategy "
        "it did not author is somebody else's work with its name on it.",
        _authored,
    ),
    Criterion(
        "survived_selection",
        "Does the best result clear what a search that wide returns from noise?",
        "Take the best of n designs where nothing has an edge and you do not "
        "get zero. Anything that does not clear that bar is the search talking.",
        _survived_selection,
    ),
    Criterion(
        "beat_the_baselines",
        "Did it beat holding the asset and doing nothing?",
        "A rule that cannot beat buying and holding has not found anything, "
        "and one that cannot beat doing nothing has found less.",
        _beat_the_baselines,
    ),
    Criterion(
        "settled",
        "Was the claim confirmed, rather than left underpowered?",
        "UNDERPOWERED means the design could not have detected the effect it "
        "set out to find. It is not a weak yes.",
        _settled,
    ),
    Criterion(
        "replicated",
        "Did it survive a deliberate, declared variation?",
        "One result on one draw of history is one number. A replication that "
        "varied nothing is a re-run.",
        _replicated,
    ),
    Criterion(
        "reviewed",
        "Did a critic attack it, and does no objection still stand?",
        "A design nobody argued with has not been reviewed. An objection that "
        "was tested and upheld is the process working; one nobody settled is "
        "an accusation left standing.",
        _reviewed,
    ),
    Criterion(
        "risk_cleared",
        "Has Risk assessed it, with no kill latch set?",
        "Risk is independent and holds a veto. A strategy it never saw is not "
        "cleared by its silence.",
        _risk_cleared,
    ),
    Criterion(
        "paper_gap_measured",
        "Has paper trading been compared against what the backtest claimed?",
        "The only measurement where the company's own claim is checked by "
        "something it does not control.",
        _paper_gap,
    ),
    Criterion(
        "chain_intact",
        "Does the company's own record verify?",
        "A recommendation resting on a ledger that does not verify is a "
        "recommendation resting on nothing checkable.",
        _chain_intact,
    ),
)
"""The twelve conditions, in the order a reader should meet them.

``live_data`` is first because it is the one the company cannot argue its way
around: everything else could be satisfied on fixtures, and satisfying them on
fixtures would prove the machinery works rather than that a market has an edge
in it. ``calibrated`` is second because it is the only condition about the
agents' own judgement rather than about a rule they wrote, and it is the one
that cannot be produced by searching harder: it accumulates at the speed of the
market, one sealed view at a time.
"""


def as_payload() -> list[dict[str, str]]:
    return [criterion.as_payload() for criterion in STANDARD]


def digest() -> str:
    """The hash of the standard as it stands.

    Recorded on every assessment. A bar lowered after it was missed is the one
    change that would make all of this worthless, and this is what makes such a
    change impossible to make quietly.
    """
    return sha256_of({"standard": as_payload()})
