# ADR-0010 — Strategies are composed, never promoted

Status: accepted · 2026-09-06
Implements: `CLAUDE.md` §1.1, §10, §16
Constrains: everything in `src/aurelis/strategy/`

## Context

The obvious way to build a strategy layer on top of a research layer is to let
a confirmed hypothesis become a strategy. It is one foreign key, the lifecycle
falls out naturally, and the inherited corpus of 125 crypto trials supplies a
ready-made pipeline of candidates.

It is also the wrong system.

A company that promotes its best measurement is a **selection engine**. It
produces whatever its corpus already contains, its output is bounded by the
size of that corpus, and it stops the day the corpus runs out. It cannot
produce anything nobody had already thought of, which is the one thing the
project is actually for.

The operator stated the distinction directly, before this milestone was built:

> The idea is not testing 125 hypotheses and using the best strategy. The idea
> is testing 125 hypotheses and more and more from more families in the future
> and not use the best strategy but start developing our hypothesis and testing
> them until the agents have THEIR strategy created by THEM.

There is a second, related trap in the same corpus. Those 125 trials were run
on **crypto alone**, and Aurelis covers seven markets. A funding-rate signal is
not a market regularity; it is a perpetual-swap regularity. Carried to equities
it produces a number that means nothing while looking exactly like a result.

## Decision

**There is no function anywhere in `strategy/` that turns a hypothesis into a
strategy.** No `promote_hypothesis`, no `from_finding`, and no `hypothesis_ref`
column on `strategy_versions`. A test asserts the absence of all of them.

What exists instead:

- `Component` — an authored piece (signal, filter, entry, exit, sizing) with a
  required rationale and a required, shape-checked `Origin` citation.
- `Synthesis.compose()` — a version is a *composition* of components plus a
  universe and a cost model.
- `StrategyLineage` — an append-only record of every act: composed, mutated,
  promoted, and by whom, in which meeting.
- `Synthesis.novelty()` — counts origins, so "did we create this?" is measured
  rather than claimed.

`Origin.DERIVED_FROM_FAILURE` is the bridge to the research layer, and the only
one. A refuted hypothesis is *material* — a component that answers it, citing
it — never a candidate. That is what a graveyard is for.

**Every version is native to exactly one desk.** `StrategyPortability` carries a
row per desk per version; everything but the native desk starts `UNPROVEN`, and
claiming `PORTED` requires evidence from a run on that desk. A component whose
declared assumptions a desk cannot structurally meet is marked `INAPPLICABLE`
at composition time, with the reason.

## Rationale

**Origins make novelty falsifiable.** A composition of five adapted components
reads as inheritance on its own page. Without a cited origin per piece, "we
built this" is unfalsifiable, and unfalsifiable claims are exactly what the
rest of this system is built to prevent.

**Citation shapes are checked because prose degrades.** `INVENTED` must cite a
meeting or task; `ADAPTED` must cite a corpus trial. An invented component
citing `MQ-H11` is not invented, and without the check that mismatch becomes
invisible the moment it is written down.

**Composition survives the corpus running out.** Components recombine.
Mutation, refinement and decomposition each produce a new version with recorded
lineage, so the space the company can reach is not bounded by what it has
already tested.

**`UNPROVEN` by default is the seven-market discipline.** The absence of a row
and a successful result look identical; an explicit `UNPROVEN` does not. This
is the structural form of "the inherited corpus covers one market of seven".

**`INAPPLICABLE` is not a bad backtest.** Telling a researcher that a funding
signal cannot run on equities is useful. Letting them run it and read the
resulting number is worse than useless.

## Consequences

- Building a strategy takes more steps than promoting one. That is the cost,
  and it is the point.
- The research layer knows nothing about strategies; the dependency runs one
  way. A change to composition cannot break a run.
- Novelty is reportable per version, so the company can see whether it is
  actually inventing or only recombining. No threshold is attached — that is a
  judgement for a Strategy Committee, not a constant in a file.
- Porting a strategy to a second desk is a research project with its own
  evidence, not a configuration change. Six of the seven desks will read
  `UNPROVEN` for a long time, honestly.

## Alternatives considered

**A `hypothesis_ref` on the version, purely as provenance.** Rejected: a column
that exists gets used, and the first time somebody wanted "the strategy for
HYP-0042" the selection engine would be back. `DERIVED_FROM_FAILURE` carries
the same information at the component level, where it belongs.

**Letting portability default to `UNPROVEN` with no `INAPPLICABLE` state.**
Rejected: it flattens two different situations, and the flatter one invites
wasted work on tests that cannot mean anything.

**A novelty threshold gating promotion.** Rejected: it would be a number nobody
could defend, and it would push authors to relabel adapted work as invented.
Measure it, show it, let the room argue.
