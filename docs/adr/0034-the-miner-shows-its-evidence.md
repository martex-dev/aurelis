# ADR-0034 — The miner shows its evidence, and a decline says why

Status: accepted · 2026-09-11

## Context

M30 and M31 put mined conjunctions to real agents, and every real agent
declined to state a mechanism — five times, on two patterns. The seat showed
them a count: this pair of events co-occurred thirty-seven times. A count is
not a reason and the models were right to say so. But it was also not enough
to reason *from*: an agent asked whether a burst of volume precedes a move,
and shown only that bursts and moves coincide, has nothing to weigh.

Nor did the record say why they declined. `MECHANISM: nothing` carried no
sentence, so five refusals were five rows saying nothing.

## Decision

### The material carries the in-sample effect, labelled as in sample

For the trigger, at six, twenty-four and seventy-two hours: how many
occurrences a recording could settle, the mean return after them, the share
that rose — and on the same recordings, the same figures after *any* bar.
Both columns are computed on the same data so the comparison is honest, and
the note under them says what they are: the reason to ask, computed on the
data the pattern was mined from, not evidence it predicts anything. The
out-of-sample predictions a stated mechanism seals as the trigger fires again
remain the only test. The evidence shown is kept as an artifact and the
mechanism names its digest.

### A decline carries a reason

`MECHANISM: nothing` may be followed by `BECAUSE:`, and the reason goes on the
ledger with the decline. A record of refusals with no reasons is a record of
nothing.

## Consequences

- **What the live evidence actually said.** After a volume spike on live
  BTC-USD, six hours later is a coin toss (up 0.55 against 0.51 for any bar)
  and twenty-four hours later the price *fell* sixty-nine percent of the time.
  The models that declined an "up" mechanism there were right. After a range
  break, in sample, the next six hours rose fifteen of sixteen times.

- **The first real mechanism.** Shown that, a Validation agent stated
  `MEC-0001`, *breakout stop-cascade momentum continuation*: a range break in
  a leveraged, thin-book asset trips clustered stops and liquidations on the
  side caught wrong, and trend-following flow chases it, so the move extends
  before it exhausts — up over six hours at 0.68. The other side: leveraged
  traders and market makers positioned against the break, and fade traders
  forced to cover. The decay: a well-known, widely-traded effect that crowds
  as capital anticipates it. It is sealed, its evidence is an artifact, and
  it predicts every future range break before the outcome exists.

- **Three other real agents still declined the same pair**, one of them the
  Critic. Sixteen occurrences is thin and a careful reader can say so. The
  mechanism now has to earn its place out of sample against the instrument's
  own drift, exactly as if nobody had believed it.

- **The response cache caught a test.** Two agents given identical prompts
  got one answer — the M25 finding again. The seat puts identity in the
  prompt; a test that bypasses the seat has to as well.
