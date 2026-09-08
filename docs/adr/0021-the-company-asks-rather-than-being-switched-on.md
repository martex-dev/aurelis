# ADR-0021 — The company asks, rather than being switched on

Status: accepted · 2026-09-08

## Context

The obvious final milestone was a live broker adapter: build it, gate it behind
configuration and a kill switch, and let the operator turn it on.

That is the wrong shape, and the person who would have to fund it said so:

> when they are ready [I want them] TO TELL ME THEMSELF that they have a
> profitable strategy worth trying and i should buy a live account

Building an adapter and switching it on makes the human decide readiness on the
company's behalf. The whole point of the organisation is that it reaches that
judgement on evidence and escalates it. So M20 is not an adapter. It is a
standard, an assessment, and an ask.

## Decision

**Ten conditions, declared in advance and hashed. Two verdicts. Only a yes
interrupts anybody.**

- `mandate/standard.py` holds `STANDARD` — ten `Criterion`s, each with the
  question it asks, why it is there, and a `check` that reads a row the company
  already writes. No self-assessment, no prose, no confidence.
- `digest()` hashes it, and every assessment records which digest it was judged
  against.
- `assess()` answers `ready` or `not_yet`. There is no third value.
- A `not_yet` is written down and **nobody is interrupted**.
- A database CHECK refuses `verdict = 'ready'` unless `met = criteria`.

## Rationale

### Why the standard is code, not a row

A row frozen by a trigger can be dropped and rewritten by anyone with the
database. A tuple in the source changes the digest that every assessment
records, so the change appears in a diff, in the history, and in the next
report — which prints, in red, that the bar moved.

**The failure to defend against is not editing the standard. It is editing it
quietly.** That distinction is what the digest buys, and it cannot be bought by
making the standard immutable, because a standard nobody may ever fix is a
standard that will eventually be wrong.

This was not hypothetical: the guard fired on its own author within an hour of
being written. The `reviewed` criterion was fixed between two assessments and
the second report said the bar had moved.

### Why a `not_yet` escalates nothing

A system that pinged its owner every time it looked would train them to stop
reading, and the one message that matters would arrive in a stream they had
learned to ignore. The refusals are still recorded — a company that kept only
the assessment that passed could not show the bar had ever held, and the bar
holding is the only reason to believe the pass.

### Why *blocked* is separated from *unmet*

Unmet is a research result: go and do better. **Blocked** means no amount of
research would help, because the machinery to produce the evidence does not
exist. Two conditions are blocked today — no desk has a wired feed, and nothing
writes a replication record — and separating them turns the standard from a
scoreboard into the company's own answer to *what should we build next*,
derived from the declared bar rather than from anybody's opinion.

## Consequences

- **After running everything this company knows how to do, it meets four of
  ten and says so.**

  ```
  BLOCKED  live_data           0 of 7 desks on live data; every one is a fixture
  MET      authored            3 strategy designs authored by an agent
  unmet    survived_selection  0 of 1 campaigns cleared the search; best surplus -0.0267
  MET      beat_the_baselines  1 of 3 attempts returned more than holding the asset
  unmet    settled             authored claims: {'underpowered': 3}
  BLOCKED  replicated          no replication has ever been recorded
  MET      reviewed            1 objection raised: 1 upheld
  unmet    risk_cleared        0 risk assessments
  unmet    paper_gap_measured  paper trading never compared against a backtest
  MET      chain_intact        chain verified: 306 events

  NOT YET — 4 of 10. Nobody was interrupted.
  ```

- **Running it found a bug in it.** The first `reviewed` check required *no
  upheld objection anywhere*. A fully exercised company fails that, because the
  M5 review ends with a critic correctly killing a survivorship-biased claim —
  so the criterion read unmet **because the company's critic had worked**. A bar
  a healthy company can never clear is not a bar, it is a bug. Upheld and
  rejected are settled; what disqualifies is an objection nobody resolved.

- **The standard names two things to build.** A live feed on one desk, and a
  writer for the replication record — the table has existed since M5 and no code
  path fills it.

- **Two more conditions have machinery but no operator command.**
  `risk_cleared` and `paper_gap_measured` are satisfiable — the paper cycle is
  built and tested — but nothing in the CLI drives it, so an operator cannot
  produce those rows. That is a gap in the operator surface, not in the
  standard, and it is recorded here rather than worked around by softening a
  criterion.

- What is *not* done: an adapter. When the answer is `ready`, the company
  escalates and stops. Buying an account remains a human act, which is the
  entire point.
