# ADR-0056 — Money is judged after costs, by episode

Status: accepted · 2026-09-25

## Context

The operator asked for the agents to work around the clock and to be ready to
earn money. The service already wakes every hour, day and night, under a
daily model-call budget. Pace was not the missing piece. The missing piece
was whether the company would recognise earning when it happened.

A mechanism becomes a candidate scheme on calibration: its sealed predictions
beat the instrument's own drift, by prediction and by episode (ADR-0040). A
scheme then trades on paper through Risk, and each round trip's P&L after
fees is recorded. Since M31 that P&L has been "reported, never judged", and
the mandate did not read it.

That leaves a hole in exactly the place the operator is looking. A scheme can
beat the drift and still lose money. The moves it calls right can be smaller
than the fees on both sides plus the slippage of an order placed an hour
after its trigger (ADR-0041). Such a scheme would keep trading on paper, and
keep being counted towards the company's case for real money, while every
round trip lost.

## Decision

### The paper record is read like the calibration record

`mechanism/earnings.py` reads a scheme's paper round trips:

- **Closed at their horizon, after fees.** A position held past its horizon
  by an outage is left out, as in M45.
- **Grouped by independent episode.** Trades are grouped by the episodes of
  the predictions they were opened on (ADR-0040), and each episode's P&L is
  their sum.
- **Counted, not summed.** An episode that made money is a win and one that
  lost is a loss. The exact sign test is on those counts, so one memecoin
  round trip that tripled cannot carry a record.
- **Drawdown.** The deepest fall of the running P&L below its high, taken
  round trip by round trip in the order they closed.

Below ten episodes the record is gathering, whatever it made.

### Earning needs the family bar; losing does not

A scheme is **earning after costs** when its total P&L is positive and its
winning episodes beat a coin at `0.05 / (schemes with ten or more episodes)`.
Calling the best of several paper books "earning" is a search, and the bar
says so.

A scheme is **losing after costs** when its total P&L is negative and its
losing episodes beat a coin at 0.05, **not** divided. The asymmetry is
deliberate. "Earning" is a claim the company may one day use to ask for real
money, so it must survive the multiple-testing correction. "Losing" only
decides whether to stop paper trading, and a stop that waited for the family
bar would let a losing scheme run for months.

Anything in between is **not distinguishable from luck**, and trading goes on.

### A scheme losing after costs stops opening positions

At each wake, before a scheme trades, its record is read. The first time it
reads "losing after costs", Risk records `mechanism.suspended` with the
numbers, and the scheme opens nothing more. Its open positions close at
their horizon. Its predictions keep being sealed and scored, so its
calibration record continues. The suspension is permanent: a scheme that
stops trading stops adding to its paper record, and it may not trade its way
back on paper luck. A new mechanism stated on the same trigger starts a new
record.

### The mandate reads it

The standard gains a fourteenth condition, **`earning`**: "Has a scheme's paper
trading made money after costs, beyond what luck gives?" It comes right after
`scheme`, because calibration without earning is not a reason to trade. The
standard's digest changes, and every assessment after this one reports that
it moved. This is intended: the bar was raised, not lowered.

## Consequences

- The mechanisms page, `aurelis mechanism trades` and the shared brain show
  each traded scheme's record after costs: its verdict, episodes won and
  lost, and drawdown. Agents stating mechanisms now see which ones paid.
- No real money moves. Live execution stays absent (ADR-0006). The path to it
  is now concrete: a scheme must be earning after costs on paper, by episode
  and beyond the family bar, together with the other conditions. Then the
  company asks, and a person decides.
- **Not done.** Sizing is still a fixed share of the paper book per scheme.
  Once a scheme is earning, its share should follow its record, which is the
  capital-allocation work the brief assigns to Portfolio.
