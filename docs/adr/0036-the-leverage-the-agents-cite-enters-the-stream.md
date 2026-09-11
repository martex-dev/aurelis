# ADR-0036 — The leverage the agents keep citing enters the stream

Status: accepted · 2026-09-11

## Context

Both mechanisms the company holds are stories about leverage. `MEC-0001`
says a range break trips clustered stops and liquidations; `MEC-0002` says a
volume spike is a liquidation cascade running out of fuel and over-leveraged
longs de-risk for a day after. Both were stated over closes, a book and a
tape. The company held no funding rate, no open interest, nothing about how
crowded anyone was. A causal story about liquidations that cannot be checked
against the leverage is a story.

## Decision

### Funding and open interest, from the perpetual, on the spot instrument

Bybit publishes without credentials every USDT linear perpetual's funding
history and hourly open interest. Read every wake, they become
`leverage.funding` (one per eight-hour settlement, the rate and its
annualised figure) and `leverage.open_interest` (one per hourly reading, with
the change over a day) — recorded on the **spot instrument entity** the
company already holds, `BTC-USD`, read from `BTCUSDT`. Two reasons. Mining
joins events on the same entity, so a funding event can only meet a price
event if they live on one. And a mechanism triggered by funding has to seal
against a close, and the closes the company records are the spot's. The
perpetual is its own entity, `derivative_of` the spot, so the provenance is
in the graph and not only in a payload field.

### Derived kinds carry their thresholds

`funding.extreme_positive` / `funding.extreme_negative` past five basis
points a settlement; `oi.surge` / `oi.purge` past ten percent over a day. The
threshold that fired is in the event. A reader of the event stream a year
from now should not have to find the constant in the code of that year.

### A settlement is a fact about its instant

The funding event's `at` is the settlement time, the open-interest event's is
the reading's own timestamp, and the raw payloads are one artifact per fetch
whose digest is *not* on the event payloads. A raw document that grows by one
row per fetch would make every fetch a "new" event; the fact is the rate at
the settlement, and the same settlement read on two wakes is one event.

### A leverage grant is its own grant

`aurelis service grant --source bybit --from-grant GRT-0002` names the same
spot symbols the universe grant reads and is read on its own step of the
wake: no bars, no catalogue, no book. A symbol with no perpetual is counted
in the note, not raised as an incident; a venue that is down is one incident
for the grant. The vendor list gained a second name and every other boundary
held — the write-scope guards, the immutable grant, the daily budget.

## Consequences

- **The judges see the leverage.** The newest-per-kind rule from M32 puts the
  funding line and the open-interest line in the material beside the book
  and the tape, so a view can cite the funding rate and the critic can check
  a liquidation story against it.

- **A mechanism can fire on funding.** The test states one on
  `funding.extreme_positive` and it seals against the spot close at the
  settlement, not a perpetual's mark.

- **Twenty-six of the thirty** live instruments have a Bybit perpetual; the
  four that do not are counted each wake.

- **Not done.** One derivatives venue; liquidation feeds, basis, options skew
  and the on-chain and social sources the brief names are each an adapter
  under the same discipline. Funding settles three times a day, so the
  derived funding kinds are slow triggers; open interest moves hourly.
