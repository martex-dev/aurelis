# ADR-0033 — The book and the tape enter the event stream

Status: accepted · 2026-09-11

## Context

Through M31 every agent and every mechanism reasoned over closes and events
derived from closes. The brief asks the company to go far past OHLCV — order
books, microstructure, flows — and says the edge most likely lives in
combinations nobody bothers to assemble. The venue the company already
records serves, without credentials, the top fifty levels of its order book
and the most recent trades with the side that took liquidity. That is real
microstructure, public, on an official API, and it was not being read.

## Decision

### Two readings per instrument per wake, as events

`book.snapshot` carries the mid, the spread in basis points, the depth within
one percent of the mid on each side, and the bid share of it. `flow.trades`
carries, over the most recent trades, taker buy volume, taker sell volume, the
buy share, and the volume-weighted price. When either is lopsided —
sixty-five percent or more to one side — a derived kind is recorded too
(`book.bid_heavy` / `book.ask_heavy`, `flow.buy_pressure` /
`flow.sell_pressure`), so a mechanism can fire on it and mining can join it
to a move.

Every reading's raw payloads are stored as one artifact and its digest
travels in the events. A reader can go and look at the fifty levels that
produced one imbalance figure. Recording the same instant twice records
nothing new.

### The trade's side is the maker's, and the module says so once

Coinbase's trade row carries the *maker's* side. A row marked `buy` had a
resting buy order that a seller hit; the aggressor sold. Read naively it
inverts every flow signal while looking exactly like a flow signal — the same
class of trap as the candle column order in `intel/live.py`. The inversion
lives in one function and a test pins it: three units on `sell` rows and one
on a `buy` row is takers buying six and selling one.

### The service reads it under the same grant

Every wake, for every instrument on a live grant, after the bars. An outage
is a warning incident and the wake continues. The judges' material shows the
newest reading of each kind first, so an hourly book snapshot does not crowd
out the one listing halt.

## Consequences

- **On the live workspace, the first readings** (2026-09-11, ~07:00Z): three
  instruments, each with depth, spread, taker flow and a raw artifact. The
  numbers are in the roadmap; whether they predict anything is not a thing
  this ADR can say and is exactly what the mechanism loop exists to find out.

- **A mechanism can fire on flow.** A test states one on `flow.buy_pressure`
  and it seals a forward prediction against the close at that instant.

- **Not done.** One venue's book, one venue's tape. Funding, basis, open
  interest, options, on-chain, social and filings remain unbuilt; each is an
  adapter under the same discipline. The readings are hourly, which is slow
  for microstructure; the service's shortest interval is fifteen minutes and
  nothing yet wakes on an event.
