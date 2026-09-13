# ADR-0043 — A reading is not a trigger, and the book closes flat

Status: accepted · 2026-09-13

## Context

Two things the live workspace showed on the morning of the 13th.

**MEC-0005.** An agent was shown the conjunction `flow.trades ⇒
leverage.open_interest ≤24h` with in-sample evidence of a 24h up-rate of
0.71 against an any-bar rate of 0.50, and stated a mechanism on it. Both
kinds are *readings*: the service records the hour's trades and the open
interest on every wake for every instrument, whether or not anything
happened. The pair therefore completes on every bar since the 11th, when
leverage recording began. The mechanism sealed 200 predictions the wake it
was stated and 26 every wake after; of the first 104 scored, 6 were right.
The in-sample "effect" was the two days the reading had existed for,
which went up, compared against four hundred bars that did not. Eight
other agents declined thirty-five sibling pairs built on `book.snapshot`
that same wake, at about five model calls each — a quarter of the day's
budget spent saying that a snapshot is not an event.

**The residuals.** The first two live paper round trips closed at the
right price and recorded the right P&L, and left a short of 129 RAY and a
long of 1 HYPE on the book. The close was sized as the open was — the same
dollar exposure — at a different price, which is a different quantity.

## Decision

### Readings are excluded from mining, and a mechanism on one is retired

`READINGS` names the kinds the service takes as a reading every wake:
`listing.seen`, `book.snapshot`, `flow.trades`, `leverage.funding`,
`leverage.open_interest`. The miner offers no pair with a reading on either
side. Derived kinds — `book.bid_heavy`, `funding.extreme_*`, `oi.surge` —
are events and stay in. The retirement sweep retires any active mechanism
whose trigger or second kind is a reading, at once and whatever its
predictions say, with the reason on the row: a mechanism that fires on
every bar predicts the calendar, not the market. MEC-0005 is retired by the
first wake on this code.

The set is declared in code rather than inferred from frequency, because
an inference would move as the recording grows, and what counts as a
reading is a fact about how the service works, not about the data.

### The in-sample baseline spans the trigger's own recording

The unconditional column of the evidence is now over the bars from the
earliest occurrence on, per recording, and the evidence says since when.
A kind recorded for two days is compared against those two days. This
does not make in-sample evidence out-of-sample — it is still labelled and
still only the reason to ask — but it removes the one confound the
service's own recording schedule introduces.

### A close is sized by the quantity the opening fill bought

`close_settled` reads the opening order's fill and closes that many units
at the newest price the wake can see. The book is flat in the instrument
afterwards. A trade whose opening order has no fill is refused with the
reason rather than closed against nothing.

An intent to the paper cycle may now carry a sixth element, the exact
quantity, and the order is capped at it. The exposure asked of Risk is a
cent above that quantity's notional, because the database's check that an
order does not exceed its approval multiplies in floating point, and an
order whose notional *equals* its approval tripped it by one ulp the first
time the test ran.

### The wake flattens what is left

After the closes, every book a mechanism has traded in is checked for a
position in an instrument no open trade accounts for. Each such residual
is closed through the same chain as any order — proposal, Risk, approval,
execution — under the version that last traded the instrument, at the
newest recorded price, and the flattening is a `mechanism.traded` event on
the book with the symbols named. A flat book writes nothing. The two live
residuals are flattened by the first wake on this code; the loss or gain
on them is the book's, on the record.

## Consequences

- The event stream keeps its readings; only their use as triggers changes.
  A mechanism on `book.bid_heavy ⇒ price.range_break` is still mineable.
- The discovery seat is shown fewer pairs, and cheaper ones: the thirty-five
  declines of the 13th would not have been asked.
- The `equity` and `weight` arguments to `close_settled` are gone; a close
  has one correct size.
- **Not done.** The baseline still compares against every bar of the same
  recordings, not against bars matched on any other property of the
  trigger's bars (time of day, volatility). Partial fills, which the paper
  broker does not produce, would also leave residuals; the sweep would
  flatten them, but nothing yet reports them as partial.
