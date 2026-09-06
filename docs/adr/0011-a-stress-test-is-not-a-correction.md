# ADR-0011 — A stress test is not a correction

Status: accepted · 2026-09-06

## Context

M5 gave the company a closed taxonomy of market defects, each with a
**mechanical test**: a Critic names a defect and the Chair runs the varied
specification the taxonomy builds for it. The rule that settled an objection
was uniform — the objection is upheld when the varied run's headline metric
gets *worse* by more than a threshold.

That rule was never checked against a world whose contents were known, because
until M10 there was no such world. The first thing the training suite did was
run all five tests over three scenarios with nothing planted in them at all.

`COST_UNDERSTATED` came back **present in every one of them.**

It is obvious in hindsight. Tripling the cost model of a rule that trades makes
that rule worse whether or not it ever had an edge. Read as "did the number get
worse", the objection is unfalsifiable: it is upheld against every
specification that turns over, including ones that lost money from the first
bar. A critic could allege it everywhere and be right by the company's own
rule, forever.

The same reasoning applies to `REGIME_SPECIFIC` and `CAPACITY_IGNORED`. Half a
window has half the return; a wider book has more names in it. Neither says
anything on its own.

## Decision

Mechanical tests are split into **two kinds**, declared on the defect:

**`CORRECTIVE`** — the varied run is the *truer* one. A hindsight universe
replaced by a point-in-time universe is not a what-if; it is the backtest the
researcher should have run in the first place. Degradation **is** the defect.
`SURVIVORSHIP` and `LOOKAHEAD`.

**`STRESS`** — the varied run is a what-if. Nobody claims costs really are
three times higher, or that the book really must be wider, or that only the
first half of the window happened. So the defect is not that the number moved.
It is that **the conclusion did not survive**: the specification showed a
result, and under the stress it does not. `COST_UNDERSTATED`,
`REGIME_SPECIFIC`, `CAPACITY_IGNORED`.

A stress objection against a specification that never showed a result settles
nothing and is not upheld.

## Rationale

This is what a review does anyway. Nobody upholds "your costs are understated"
against a strategy that already lost money — the objection has no target. What
the old rule did was let that be written down as a defect caught, and there was
no way to notice, because a real review has no answer key.

The suite has one. Twelve worlds, three of them empty, and a rule that finds
defects in the empty ones is visibly wrong within seconds of being run. That is
the argument for building the scenarios at all, and it paid for itself before
the first agent was scored.

Two smaller findings came out of the same run and are recorded here because
they have the same shape:

- **The `LOOKAHEAD` test was a provable no-op.** It set the warm-up to one
  lookback, and every registered signal already holds nothing during its own
  lookback — so the varied run was byte-identical to the original, every time,
  for every specification the objection had ever been raised against. It is now
  twice the lookback, and it lengthens the window by one lookback at the same
  time so that both sides trade the same number of bars. Without that, the
  varied run would trade a shorter history, any rule with a real edge would do
  worse over less time, and the defect would be indistinguishable from the
  handicap.

- **A builder may now vary two fields**, which M5 forbade. The rule was a proxy
  for the real requirement — that a test change exactly one thing *about the
  question* — and the second field exists precisely to hold everything else
  constant. The test that enforced the old rule now asserts the trading-bar
  count is equal on both sides, which is a stronger statement than counting
  fields.

## Consequences

- `MarketDefect` carries a `kind`. Adding a defect to the taxonomy now requires
  saying which sort of question it asks, which is the right thing to be forced
  to decide.
- A playbook check carries two thresholds: how far the number must move, and —
  for a stress test — how low the stressed run must land. Both are versioned
  and both are gated on the suite.
- Objections already recorded under the old rule were settled by a rule that
  could not fail for three of the five defect types. Nothing is rewritten:
  the M5 review that killed a survivorship claim used a corrective test and
  stands. Any future audit of upheld cost, regime or capacity objections should
  know they were judged by the older rule.
- `CAPACITY_IGNORED` currently has **no scorable scenario**. The plant is in the
  catalogue, the measurement says it did not take, and the suite reports the
  hole rather than tuning until it agreed. Closing it is M11 work.
