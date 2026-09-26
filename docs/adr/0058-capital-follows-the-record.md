# ADR-0058 — Capital follows the record

Status: accepted · 2026-09-26

## Context

ADR-0056 judged each scheme's paper trading after costs, by episode, and left
one thing undone: "Sizing is still a fixed share of the paper book per
scheme." On reading the code, it was worse than a fixed share.
`trade_firings` sized every position at `equity × 5%` from a constant. The
allocation row it wrote was never read again, and nothing ever withdrew one.
A scheme earning after costs and a scheme indistinguishable from luck were
the same size. The Portfolio Manager, whose charter is capital allocation,
decided nothing after the first day.

## Decision

- **A declared ladder** (`mechanism/sizing.py`): a scheme still gathering,
  or not distinguishable from luck, gets 5% of the paper book. One earning
  after costs gets 10%. One losing after costs gets nothing, and it is
  suspended anyway. The ladder is written down rather than fitted: a sizing
  formula tuned to the record would be one more parameter mined on the past.
- **Schemes together hold at most half the book.** A new or larger share is
  cut to the room left under that cap and under the book's own limit of 1.0.
- **Positions are sized from the live allocation.** `trade_firings` reads the
  scheme's live allocation for the book instead of a constant. A scheme whose
  share is zero opens nothing and says why.
- **The Portfolio Manager re-reads the record daily** (a sixth duty in
  ADR-0057's table). Where the ladder gives a different share, the manager
  withdraws the old allocation (`portfolio.allocation_withdrawn`, with the
  reason) and records the new one, with the record in its rationale. A share
  that already matches its record is left alone.
- Risk still assesses every order. The share is what Portfolio asks for, not
  what Risk must grant.

## Consequences

- A scheme that earns after costs, by episode and beyond the family bar,
  trades at twice the size. A scheme that loses stops. That is the whole
  path from a record to more paper capital. Real capital still waits for the
  mandate and a person.
- The mechanisms page shows each scheme's share of the book.
- **Not done.** Two schemes that fire on the same moves are sized
  independently. Correlation-aware sizing belongs to Portfolio's
  correlation research (the brief's §11), and needs more paper history than
  exists yet.
