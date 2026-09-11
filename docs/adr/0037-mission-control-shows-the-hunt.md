# ADR-0037 — Mission Control shows the hunt

Status: accepted · 2026-09-11

## Context

By M35 the company's most important work happened in a loop nobody could
watch: conjunctions mined, evidence shown, agents declining with reasons or
stating a mechanism, predictions sealing across thirty instruments, outcomes
arriving. The mechanisms page was one table with a verdict column. Reading a
mechanism's causal story, seeing what its author was shown, or learning that
four other agents had declined the same pattern and why, meant opening the
database. The brief says the station is the primary interface and the user
should never have to.

## Decision

### Every mechanism has a page

`/mechanism/<ref>`: the statement (why, the other side, the decay), what the
agent was shown unfolded from the evidence artifact — the pattern's count and
the in-sample effect beside the unconditional, labelled as in sample — the
record (predictions, scored, right, Brier, the unconditional base rate), the
tally by instrument, every prediction with its outcome and a link to its
thesis, the paper trades, and the other agents who were shown the same
trigger and declined, with their reasons. The verdict is the library's; the
page draws it.

### The mechanisms page shows the declines

Under the table, "Declined, and why": who was shown which conjunction, when,
and the sentence they gave. A record of refusals with reasons is most of what
the company knows about which patterns are coincidences, and it was on the
ledger where no one read it.

### The page computes nothing

Every figure comes from the mechanism library's status or the resolver's
rows; the page has no arithmetic of its own. That is the rule the station has
followed since M7 and it is what let the M35 base-rate display bug be a
one-line fix rather than a second definition.

## Consequences

- **On the live workspace** the page for `MEC-0002` shows the volume-spike
  story beside the four declines that call the same pattern volatility
  clustering, eighty-six predictions across the universe with one scored so
  far, and the base rate it has to beat. Whether it will is not the page's
  to say.

- **The tally by instrument said something the table could not.** Twenty-six
  of those eighty-six predictions are on `VTHO-USD` and thirteen on
  `RAY-USD`: a small coin's hourly volume spikes fire a volume trigger far
  more often than bitcoin's, so a mechanism about leveraged liquidation
  cascades will be judged mostly on instruments with the least leverage on
  them. The page shows the concentration; what to do about it — a trigger
  that scales to the instrument's own volume, or a scheme that sizes by
  liquidity — is a later milestone's question, and now a visible one.

- **Not done.** The facility drawing is still the M7 monospace-and-SVG
  building, not the pixel-art research complex the brief describes; that is
  its own milestone. The judges' theses already had pages; the world events
  do not, and a mechanism's trigger occurrences cannot yet be clicked
  through to the event that fired.
