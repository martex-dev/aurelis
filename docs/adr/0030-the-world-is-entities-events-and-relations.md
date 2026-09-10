# ADR-0030 — The world is entities, events and relations, and price is one event type

Status: accepted · 2026-09-11

## Context

Everything the company held was a price series sampled at intervals. Every
source served bars, every experiment walked bars, every view was a function
of past closes. The brief names the kind of thing this company is supposed to
find — a token posted in two communities within hours while a known-early
wallet cluster starts buying — and says plainly that nothing in that sentence
is a price series. It needs entities, events, relations, conjunctions inside a
time window, and rare events with short horizons. The current ontology could
not represent, store, mine or test any of it: not because the design space
was too small, because the world model was the wrong shape.

## Decision

### Three tables, one of them append-only by trigger

**Entities** have a kind, a key stable within the kind, attributes, a source
and a first-seen time. An instrument, an asset, a venue today; a wallet, an
account, a community later, with no schema change.

**Events** are typed, timestamped twice (when it happened, when the company
learned it), about one entity, with a payload and a source, and hashed over
what happened so the same fact learned twice is one row and a fact that
differs by a field is a new one. The table refuses updates and deletes.

**Relations** are typed edges between entities with a source, append-only.

### Price is one event type, and only its notable moments enter the stream

The bars stay in their recordings. What enters the stream is derived from them
deterministically, with the recording as the source: a volume spike (a bar at
three times the median of the prior 168) and a range break (a close above the
prior 168-bar high or below its low). Deriving is idempotent.

### The first non-price source is the venue's own catalogue

Coinbase publishes its product list without credentials. Read on every wake
and diffed against what the company holds, it is a stream of events the
brief's mechanisms need: a product seen for the first time, a status change,
a trading halt, a disappearance. The first sync marks its events
`first_sync: true`, because a thousand initial sightings are a fact about the
company seeing the catalogue and not about a thousand listings in one day.

### Queries over windows are the primitive a scheme is built from

Events for an entity since a moment; events of a kind between two moments;
the co-occurrence of two kinds on the same entity inside a window. The last
returns a list of conjunctions, and the command that prints it says in its
footer what a conjunction is not: a discovery. A mined pattern becomes one
only when an agent states a mechanism — why it would work, who is on the
other side, what constraint makes it persist — and the mechanism predicts
something else that is then tested. That machinery is not built here; the
data it needs now is.

### The judges see it

The material a judge is shown gains a section of the recent events for the
instrument it chose, rendered with the payload's figures so a view may cite
them. It is the first thing a judge has seen that is not a close.

## Consequences

- **On the live workspace:** 837 products became entities, with their status
  — several already `delisted` and `trading_disabled` — and their base and
  quote assets and venue as relations. Sixty price events were derived from
  the three live recordings. The first co-occurrence query, spike then break
  within a day, returned 37 pairs on BTC-USD alone. Every one of those pairs
  is a conjunction and none is a scheme.

- **The service syncs the catalogue and derives events every wake**, under
  the same grant as the bars, and a catalogue outage is an incident like any
  other.

- **The stream holds nothing off-venue yet.** No social posts, no on-chain
  flows, no filings. Each is a source with its own adapter, its own grant and
  its own recording discipline; the shape they land in is now here.

- **Additive migration carried this.** Three new tables and no new columns on
  old ones; a workspace made before this milestone gains them on init.
