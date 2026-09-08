# ADR-0022 — Live data is a recording, and a replication must vary

Status: accepted · 2026-09-08

## Context

M20's standard reported two conditions as **blocked** — not merely unmet, but
unsatisfiable by any amount of research, because the machinery to produce the
evidence did not exist:

- `live_data` — every number the company held was computed on a fixture.
- `replicated` — the `replications` table had existed since M5 with a docstring
  explaining exactly what it was for, and **nothing had ever written a row into
  it.** The record shape was built and the act it records was not.

Separating *blocked* from *unmet* was the point of that design, and this is the
company acting on its own answer.

## Decision

### Live data enters as a hashed recording, never as a connection

The thing to get right is not the HTTP call. It is that **an experiment cannot
be reproduced against a moving endpoint.** Every preregistration here locks a
spec and every run records a `data_fingerprint`, and both are worthless if the
bars behind them change between two runs of the same experiment. A company that
pointed its engine at a live URL would have replaced reproducible research with
a moving target and kept all of the vocabulary.

So a fetch is an event with a record: `MarketSnapshot` carries the vendor, the
endpoint, the window, the bar count and a hash of every bar; `SnapshotBar`
stores prices as text for exactness; `verify()` rehashes on demand, the same
standard the artifact store and the event chain are held to.

`SnapshotSource` then serves the snapshot through exactly the
`MarketDataSource` protocol the fixtures use. **The engine cannot tell the
difference, and must not be able to** — real data is not a second research
pipeline, it is the same pipeline with a source whose bars came from a market.

### A replication must vary something, from a closed set

Every engine here is deterministic, so re-running an identical specification
returns an identical number, and learning that determinism holds is not
evidence about a market. `Variation` is therefore closed — `SEED`,
`SHORTER_WINDOW`, `EARLIER_WINDOW` — and `vary()` is a pure function that never
touches the signal, the costs or the universe basis.

The criteria are **inherited** from the lock, never re-chosen. That is the
whole reason a replication spends no error budget: it asks whether one
already-declared result survives a declared perturbation, and a replication
free to pick its own bar afterwards would be a second bet wearing the word.

## Consequences

- **The company has seen a market.** 3000 hourly BTC-USD bars from Coinbase's
  public endpoint, 6 May to 8 September 2026, hashed and verifying, and the
  `live_data` condition reads MET.

- **It does not make the research powered.** A few thousand hourly bars is four
  months; `desks/power` says settling an annualised Sharpe of 0.5 on this desk
  needs about fifteen years of them. Real data makes the research *about a
  market*; it does not make an underpowered claim settleable, and the mandate
  keeps saying so.

- **The mandate reads the data rather than a flag.** `live_data` checks the
  snapshot table, not `desk_openings.data_is_live` — a hashed recording of bars
  that genuinely traded is a fact, and a boolean on an opening is whatever the
  code that wrote it believed. A fixture may be ingested the same way for
  testing and is stored with `is_live = False`, so the two can never be told
  apart by whoever remembers which is which.

- **The first replication run found a bug in the judgement.** Three variations
  of an underpowered registration all came back underpowered, the verdicts
  matched, and every one was recorded as `held`. Same verdict is not the same
  as a result surviving — and `memory/confidence.py` counts `held` rows as
  evidence, so replications of nothing would have accumulated into confidence
  about nothing. `NOTHING_TO_REPLICATE` now exists and is checked first.

- **The pagination loop could not stop.** It walked `end` backwards a page at a
  time and terminated only on an empty page, so a vendor returning overlapping
  data would loop past the epoch until `fromtimestamp` raised an `OSError`. The
  condition is now *progress* — a page that adds no new bars ends the walk —
  with an epoch floor behind it. Found by a recorded payload that ignored the
  window, which is exactly the case a live vendor could produce.

- **The first result that genuinely held was still wrong.** Replicating M5's
  registration under a `SEED` variation returns `confirmed -> confirmed`,
  `HELD` — and that is the survivorship-biased rotation claim the M5 review
  then killed on an upheld objection. A stable result and a correct one are
  different things: replication tests whether a number survives a
  perturbation, not whether the specification that produced it was honest.
  Both records now exist against the same registration, which is the right
  outcome and a good argument for keeping them separate.

- **Nothing in the test suite touches the network.** `CandleFeed` is a protocol
  and every test passes a recorded payload. `aurelis data fetch` is the one
  command that reaches a market, it asks before it does, and it is the only
  place in the repository that does.

- **Nothing is blocked any more.** Every remaining condition on the standard is
  now a research result rather than a missing capability, which is a harder
  place for the company to be and the right one.
