# ADR-0041 — Paper fills at the price the wake can see

Status: accepted · 2026-09-12

## Context

A scheme's paper position opened at the trigger bar's close and closed at
the resolution bar's close. Both are the prices the *prediction* is scored
against, and both are prices the *order* could not have got: the service
wakes hourly, so an order on a trigger at 14:00 is placed at 15:00, when the
14:00 close is history. For a momentum mechanism — a break, then
continuation — the hour between the trigger and the order is where much of
the move is, and a fill at the trigger's close books it as profit the
company never had. The realised P&L was flattered on every trade in a way
that favoured exactly the mechanisms the company was finding.

## Decision

### An order fills at the newest close the wake can see

At the wake, the newest bar at or before the moment from the instrument's
newest recording. That is what a trader at the wake could have dealt near.
The fill price and the bar it came from are recorded on the trade.

### No price as new as the trigger, no position

If the newest recorded bar is older than the trigger bar, the wake cannot
see a price the trigger has already moved, and the firing is refused with
the reason on the result. On a venue this does not happen; on a fixture
whose recording runs past the frozen clock it happens by construction, and
the tests say so.

### A settled position closes at the newest close, or waits

At the wake after the horizon passes, the position closes at the newest
close the wake can see. If no bar newer than the entry has been recorded yet
it stays open and the result says so; it never closes at the entry.

### The slippage is on the record

The difference between the trigger's close and the fill, in basis points,
signed so that positive is worse for the position. Reported beside the P&L
by the CLI and shown as entry and exit on the mechanism's page, with a note
under the table saying what the columns are.

## Consequences

- **Paper P&L is now executable P&L**, less fees, at the granularity the
  company records. It is still paper: the mark is a close, not a book, and
  the book the company reads every wake is the next refinement.

- **Two positions on the live workspace** were opened under the old rule at
  the trigger close; they close under the new one at the wake's close. The
  entry columns for them are empty, which is the honest reading of orders
  placed before the price was recorded.

- **The M31 scheme test moved its clock.** It seeded a firing from a
  recording that ran past the frozen clock; the wake now refuses to fill a
  trigger it cannot yet see, so the test stands where a wake would.
