"""What stands between an authored version and a paper book, read from the record.

M20's mandate reported ``risk_cleared`` and ``paper_gap_measured`` as unmet with
a note that they were *satisfiable* — the paper cycle was built and tested, and
no command drove it. This module is the half of that gap worth building first,
because the interesting question turned out not to be "how do we start paper
trading?" but **"what is actually stopping us?"**

The answer has always been the promotion gates. A version reaches a paper book
only through :meth:`~aurelis.strategy.lifecycle.Strategies.promote`, which
refuses unless every registered gate was evaluated and every one passed. So the
operator command that was missing is not a switch. It is a reader: seven gates,
seven observables, each fetched from somewhere the company already wrote down.

**Nothing here computes a number an agent could have chosen.** Every reader
either finds its observable in the record or returns :attr:`Evidence.silent`
with a sentence saying what is absent. That distinction is the whole design:

* A gate the record *answers* is evaluated against its registered criterion,
  and it may well fail. A failure is a result.
* A gate the record is *silent* on is not evaluated, and the promotion is
  refused for that reason. Substituting a default would be inventing evidence,
  and a default of zero is the direction that promotes things.

Two silences found by writing this are worth naming, because both are holes in
:func:`~aurelis.strategy.gates.default_criteria` rather than in the data:

**Gate F counts sealed queries and passes at zero.** Its own note says "and it
must have passed", but ``sealed_queries_used lte 1`` is satisfied most easily by
never asking. A version that never touched the held-out data has not cleared
custody — it avoided it — so the reader returns silence rather than the zero the
criterion would have accepted.

**Gate D counts open critical objections and passes at zero.** Same shape: a
design nobody read has none. The reader returns silence when no objection was
ever raised against the version at all, and the count when a critic did look.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.authoring.tables import AuthoringAttempt
from aurelis.core.errors import IntegrityViolation
from aurelis.intel.snapshots import MarketSnapshot, SnapshotBar
from aurelis.meetings.tables import MeetingObjection
from aurelis.research.tables import Registration, Replication, Result, Run
from aurelis.strategy.gates import COMPARISONS, default_criteria
from aurelis.strategy.states import Gate
from aurelis.strategy.tables import StrategyVersion

__all__ = [
    "BENCHMARK",
    "Evidence",
    "PARTICIPATION",
    "Readiness",
    "TRIAL_SHARPE_VARIANCE",
    "gather",
    "intended_notional",
    "unmet",
]

BENCHMARK = "always_long"
"""Which reference gate B measures the excess against.

Buy-and-hold, not the better of the two baselines. ``never_trade`` is a floor
rather than a benchmark, and a version that beat only the floor would clear a
gate whose note says "same instruments, window and costs as the desk benchmark"
without having beaten anything anyone could have held.
"""

PARTICIPATION = Decimal("0.01")
"""The share of one bar's traded value the company assumes it could take.

Declared here rather than passed in, because a capacity ratio is a statement
about the market and the assumption behind it has to travel with it. One per
cent of a bar is the conventional conservative figure; it is an assumption, it
is not measured, and :attr:`Evidence.source` says so on every row it produces.
"""

TRIAL_SHARPE_VARIANCE = 0.25
"""Variance of Sharpe across the trials gate A deflates against.

The same assumption martex-quant's own default makes. Stated because the
deflated Sharpe is only as honest as this number: understate the spread of what
the search produced and the benchmark it must clear falls with it.
"""


@dataclass(frozen=True, slots=True)
class Evidence:
    """One gate's observable, or the reason the record cannot supply it."""

    gate: Gate
    metric: str
    value: Decimal | None
    source: str
    """Where the number came from, precisely enough to go and look."""

    @property
    def silent(self) -> bool:
        """Whether the record has nothing to say.

        Distinct from a value of zero throughout. "Nobody measured this" and
        "this measured zero" differ in exactly the direction that matters: one
        of them promotes strategies.
        """
        return self.value is None

    def describe(self) -> str:
        if self.silent:
            return f"{self.gate.value} {self.metric}: SILENT — {self.source}"
        return f"{self.gate.value} {self.metric}: {self.value} ({self.source})"


@dataclass(frozen=True, slots=True)
class Readiness:
    """Every gate on one version, and what the record can say about each."""

    version_ref: str
    attempt_ref: str
    evidence: tuple[Evidence, ...]

    @property
    def silent(self) -> tuple[Evidence, ...]:
        return tuple(item for item in self.evidence if item.silent)

    @property
    def answerable(self) -> tuple[Evidence, ...]:
        return tuple(item for item in self.evidence if not item.silent)

    @property
    def complete(self) -> bool:
        """Whether every gate has an observable. Not whether they passed."""
        return not self.silent

    def describe(self) -> str:
        lines = [item.describe() for item in self.evidence]
        if self.silent:
            lines.append(
                f"{len(self.silent)} of {len(self.evidence)} gates cannot be "
                "evaluated: the record does not hold the observable"
            )
        return "\n".join(lines)


# ------------------------------------------------------------ the readers


def _decimal(raw: object, *, what: str) -> Decimal:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError) as error:
        raise IntegrityViolation(
            f"{what} is recorded as {raw!r}, which is not a number"
        ) from error


def _observations(session: Session, attempt: AuthoringAttempt) -> int | None:
    """How many bars the locked specification ran on.

    Read from the registration rather than recounted, so the figure gate A
    deflates against is the one the preregistration committed to.
    """
    registration = session.execute(
        sa.select(Registration).where(Registration.ref == attempt.registration_ref)
    ).scalar_one_or_none()
    if registration is None:
        return None
    data = registration.spec.get("data") if isinstance(registration.spec, dict) else None
    if not isinstance(data, dict):
        return None
    bars = data.get("bars")
    return int(bars) if isinstance(bars, int) and bars > 0 else None


def _statistical(session: Session, attempt: AuthoringAttempt) -> Evidence:
    """Gate A: the observed Sharpe deflated by the trials that produced it."""
    gate, metric = Gate.A_STATISTICAL, "deflated_sharpe"
    raw = attempt.metrics.get("sharpe")
    if raw is None:
        return Evidence(
            gate,
            metric,
            None,
            f"{attempt.ref} recorded no sharpe, so there is nothing to deflate",
        )
    observations = _observations(session, attempt)
    if observations is None:
        return Evidence(
            gate,
            metric,
            None,
            f"{attempt.registration_ref} does not state how many bars it "
            "locked; a deflation needs the observation count it was measured on",
        )

    from aurelis.engines.martex import MartexStatistics
    from aurelis.engines.protocol import EngineUnavailable

    try:
        computed = MartexStatistics.deflate(
            _decimal(raw, what=f"{attempt.ref} sharpe"),
            n_observations=observations,
            n_trials=attempt.trials_in_family,
            trial_sharpe_variance=TRIAL_SHARPE_VARIANCE,
        )
    except EngineUnavailable as error:
        return Evidence(gate, metric, None, str(error))
    return Evidence(
        gate,
        metric,
        computed.value,
        f"{computed.method} on {observations} bars from {attempt.run_ref}, "
        f"{attempt.trials_in_family} trials in {attempt.ref}'s family, "
        f"trial sharpe variance assumed {TRIAL_SHARPE_VARIANCE}",
    )


def _benchmark(attempt: AuthoringAttempt) -> Evidence:
    """Gate B: Sharpe against buy-and-hold on the same window and costs."""
    gate, metric = Gate.B_BENCHMARK, "excess_sharpe_over_benchmark"
    raw = attempt.metrics.get("sharpe")
    reference = attempt.baselines.get(BENCHMARK) if attempt.baselines else None
    if raw is None or not isinstance(reference, dict) or "sharpe" not in reference:
        return Evidence(
            gate,
            metric,
            None,
            f"{attempt.ref} does not carry both a sharpe and a {BENCHMARK} "
            "baseline, so the excess cannot be taken",
        )
    observed = _decimal(raw, what=f"{attempt.ref} sharpe")
    against = _decimal(reference["sharpe"], what=f"{attempt.ref} {BENCHMARK} sharpe")
    return Evidence(
        gate,
        metric,
        observed - against,
        f"{attempt.ref}: sharpe {observed} against {BENCHMARK} {against}, "
        "same window, same costs, same instruments",
    )


def _independence(
    session: Session, attempt: AuthoringAttempt, *, portfolio_ref: str | None
) -> Evidence:
    """Gate C: correlation against everything already allocated."""
    from aurelis.portfolio.tables import Allocation

    gate, metric = Gate.C_INDEPENDENCE, "max_correlation_with_deployed"
    if portfolio_ref is None:
        return Evidence(
            gate,
            metric,
            None,
            "no book was named, so there is no set of deployed versions to "
            "correlate against",
        )
    deployed = [
        ref
        for ref in session.execute(
            sa.select(Allocation.version_ref).where(
                Allocation.portfolio_ref == portfolio_ref,
                Allocation.withdrawn_at.is_(None),
            )
        ).scalars()
        if ref != attempt.version_ref
    ]
    if not deployed:
        # A genuine zero rather than a silence. An empty book has no overlap
        # with anything, and that is a fact about the book, not a gap in it.
        return Evidence(
            gate,
            metric,
            Decimal("0"),
            f"{portfolio_ref} holds no other version; there is nothing for "
            f"{attempt.version_ref} to overlap with",
        )
    return Evidence(
        gate,
        metric,
        None,
        f"{portfolio_ref} holds {len(deployed)} other version(s) and no return "
        "series has been recorded for them; a correlation this gate could cite "
        "would have to come from the engines, not from this module",
    )


def _integrity(session: Session, attempt: AuthoringAttempt) -> Evidence:
    """Gate D: open critical objections against anything in this version's chain.

    Silent when nobody ever objected. Zero open objections against a design no
    critic read is the absence of a review, not the result of one, and this
    gate exists to catch planted defects — which are found by looking.
    """
    gate, metric = Gate.D_INTEGRITY, "open_critical_objections"
    targets = {
        attempt.version_ref,
        attempt.strategy_ref,
        attempt.registration_ref,
        attempt.hypothesis_ref,
        attempt.run_ref,
    }
    rows = list(
        session.execute(
            sa.select(MeetingObjection.status, MeetingObjection.severity).where(
                MeetingObjection.target.in_(sorted(targets))
            )
        ).all()
    )
    if not rows:
        return Evidence(
            gate,
            metric,
            None,
            f"no objection has ever been raised against {attempt.version_ref} "
            "or anything in its chain. Zero open objections against a design "
            "nobody read is the absence of a review, not the result of one",
        )
    open_critical = sum(
        1 for status, severity in rows if status == "open" and severity == "critical"
    )
    return Evidence(
        gate,
        metric,
        Decimal(open_critical),
        f"{len(rows)} objection(s) raised against {attempt.version_ref}'s "
        f"chain, {open_critical} of them critical and still open",
    )


def _replication(session: Session, attempt: AuthoringAttempt) -> Evidence:
    """Gate E: replications of this version's registration that held."""
    gate, metric = Gate.E_REPLICATION, "surviving_replications"
    rows = list(
        session.execute(
            sa.select(Replication.outcome).where(
                Replication.parent_registration_ref == attempt.registration_ref
            )
        ).scalars()
    )
    held = sum(1 for outcome in rows if outcome == "held")
    return Evidence(
        gate,
        metric,
        Decimal(held),
        f"{len(rows)} replication(s) of {attempt.registration_ref}, {held} held "
        "under a declared variation",
    )


def _custody(session: Session, attempt: AuthoringAttempt) -> Evidence:
    """Gate F: counted queries against the sealed split.

    Silent at zero rather than passing. ``sealed_queries_used lte 1`` is
    satisfied most easily by never asking, and the gate's own note requires
    that a query happened *and passed*. A criterion that counts cannot express
    that, so the reader refuses to supply the zero it would accept.
    """
    gate, metric = Gate.F_CUSTODY, "sealed_queries_used"
    runs = list(
        session.execute(
            sa.select(Run.ref).where(Run.registration_ref == attempt.registration_ref)
        ).scalars()
    )
    used = 0
    if runs:
        used = int(
            session.execute(
                sa.select(sa.func.count())
                .select_from(Result)
                .where(Result.run_ref.in_(runs), Result.split == "sealed")
            ).scalar_one()
        )
    if not used:
        return Evidence(
            gate,
            metric,
            None,
            f"no sealed query has ever been released for {attempt.version_ref}. "
            "The criterion counts queries and is satisfied by zero, but its own "
            "note requires that one happened and passed: a version that never "
            "touched the held-out data avoided custody rather than clearing it",
        )
    return Evidence(
        gate,
        metric,
        Decimal(used),
        f"{used} sealed quer(y/ies) released against {attempt.registration_ref}",
    )


def _capacity(
    session: Session, attempt: AuthoringAttempt, *, intended: Decimal
) -> Evidence:
    """Gate G: tradable value per bar against the size intended for it.

    Computed from a recorded snapshot's own volume: the median bar's traded
    value, times the participation share the company assumes it could take,
    divided by the notional the allocation would put to work. A ratio of 1
    means the intended size is exactly one bar's assumed fill.

    Requires real bars. There is no volume in a fixture worth dividing by, and
    a capacity claim resting on invented volume is the kind of number that
    reads as diligence and contains nothing.
    """
    gate, metric = Gate.G_CAPACITY, "capacity_over_intended_allocation"
    if intended <= 0:
        return Evidence(
            gate,
            metric,
            None,
            "the intended allocation is zero, and a capacity ratio over zero "
            "size is not a fact about the market",
        )
    snapshot = session.execute(
        sa.select(MarketSnapshot)
        .where(MarketSnapshot.desk == attempt.desk, MarketSnapshot.is_live.is_(True))
        .order_by(MarketSnapshot.fetched_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if snapshot is None:
        return Evidence(
            gate,
            metric,
            None,
            f"no recorded market data exists for the {attempt.desk} desk, and "
            "capacity is a claim about traded volume",
        )
    values = [
        Decimal(close) * Decimal(volume)
        for close, volume in session.execute(
            sa.select(SnapshotBar.close, SnapshotBar.volume).where(
                SnapshotBar.snapshot_ref == snapshot.ref
            )
        ).all()
    ]
    if not values:
        return Evidence(
            gate, metric, None, f"{snapshot.ref} holds no bars to measure volume on"
        )
    median = Decimal(str(statistics.median(sorted(values))))
    ratio = (median * PARTICIPATION / intended).quantize(Decimal("0.0001"))
    return Evidence(
        gate,
        metric,
        ratio,
        f"{snapshot.ref} ({snapshot.symbol} {snapshot.interval}, {snapshot.bars} "
        f"bars): median bar traded {median.quantize(Decimal('0.01'))}, "
        f"{PARTICIPATION} of it assumed available, against {intended} intended",
    )


# ------------------------------------------------------------- the gather


def gather(
    session: Session,
    *,
    version_ref: str,
    portfolio_ref: str | None = None,
    intended: Decimal = Decimal("0"),
) -> Readiness:
    """Read every gate's observable out of the record.

    ``intended`` is the notional the allocation would put to work — weight
    times the book's equity. It is the denominator gate G divides by, and it is
    supplied rather than looked up because a capacity ratio is a claim about a
    *proposed* size, which does not exist in the record until the deployment
    it justifies has happened.
    """
    version = session.execute(
        sa.select(StrategyVersion).where(StrategyVersion.ref == version_ref)
    ).scalar_one_or_none()
    if version is None:
        raise IntegrityViolation(f"no strategy version {version_ref}")

    attempt = session.execute(
        sa.select(AuthoringAttempt).where(AuthoringAttempt.version_ref == version_ref)
    ).scalar_one_or_none()
    if attempt is None:
        raise IntegrityViolation(
            f"{version_ref} was not authored through a recorded attempt, so "
            "there is no measurement, no locked registration and no trial "
            "count behind it. Every gate here reads from that attempt; a "
            "version composed by hand has to be evidenced by hand"
        )

    return Readiness(
        version_ref=version_ref,
        attempt_ref=attempt.ref,
        evidence=(
            _statistical(session, attempt),
            _benchmark(attempt),
            _independence(session, attempt, portfolio_ref=portfolio_ref),
            _integrity(session, attempt),
            _replication(session, attempt),
            _custody(session, attempt),
            _capacity(session, attempt, intended=intended),
        ),
    )


def unmet(readiness: Readiness, desk: str) -> tuple[str, ...]:
    """Which answerable gates fail their own criterion, described.

    Pure: reads the same ``default_criteria`` the registration uses, and
    compares. Does not touch the database, so a caller can show an operator
    what would happen before anything is written.
    """
    criteria = default_criteria(desk)
    failures: list[str] = []
    for item in readiness.answerable:
        criterion = criteria[item.gate]
        comparison = str(criterion["comparison"])
        bound = Decimal(str(criterion["value"]))
        observed = item.value
        if observed is None or not COMPARISONS[comparison](observed, bound):
            failures.append(
                f"{item.gate.value}: {item.metric} {observed} is not "
                f"{comparison} {bound}"
            )
    return tuple(failures)


def intended_notional(
    session: Session, *, portfolio_ref: str, weight: Decimal
) -> Decimal:
    """Weight times the book's equity: the size a capacity ratio divides by."""
    from aurelis.portfolio.tables import Portfolio

    equity = session.execute(
        sa.select(Portfolio.initial_equity).where(Portfolio.ref == portfolio_ref)
    ).scalar_one_or_none()
    if equity is None:
        raise IntegrityViolation(f"no portfolio {portfolio_ref}")
    return (Decimal(equity) * weight).quantize(Decimal("0.01"))
