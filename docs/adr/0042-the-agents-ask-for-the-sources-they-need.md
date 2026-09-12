# ADR-0042 — The agents ask for the sources they need

Status: accepted · 2026-09-12

## Context

The brief names social posts and news as raw material, and asks that the
agents decide what they need. The operator's constraint, stated on the 12th,
is that every source be free: no paid tier, no key the company has to hold.
And the company's own rule since M27 is that it fetches nothing a person did
not grant.

Three constraints, one design.

## Decision

### A catalogue of free, official, keyless feeds, fixed by a person

Publishers' own RSS feeds are official syndication, public, and cost
nothing: CoinDesk, Cointelegraph, The Block, Decrypt. They are the whole
catalogue. GDELT was tried and throttled the first request; anything that
needs a key is out by construction. A source enters the catalogue by a code
change, which is a person's decision on the record.

### Which of them the company reads is an agent's decision, with a reason

A Market Intelligence agent is shown the catalogue, what each source covers,
the instruments the company follows and what is already read, and answers
`SOURCES: ...` and `BECAUSE: ...`, or `none` and why. A name outside the
catalogue is refused. Every answer is a row and a ledger event. The loop's
`source` action seats each such agent once per catalogue; a new source in
the catalogue is a new question.

### The service reads the union, under a grant for the class

`aurelis service grant --source news --from-grant GRT-0002` records, once,
that the service may read whatever catalogue feeds the agents ask for,
matched against those spot symbols. A news grant fetches no bars. No
request, nothing read, and the wake's note says so.

### A headline is an event on every instrument it names, at its own time

Matched by ticker as an upper-case word or by a short alias table, with the
tickers that are English words matched only by alias. `news.mention` at the
headline's published time, so mining joins it to price events on the same
entity and a mechanism seals against the spot close. `news.burst` when an
instrument's mentions in six hours are at least three and at least three
times its trailing week's six-hour rate, with the threshold in the event.
The same headline read on ten wakes is one event.

## Consequences

- **The judges see headlines** beside the book, the tape and the funding,
  by the newest-per-kind rule, and can cite them.

- **A mechanism can fire on attention.** A test states one on `news.burst`
  and it seals a forward prediction against the spot close at the burst.

- **The offline company asks for two sources** through a stand-in, so CI
  exercises the seat, the grant and the wake without a network.

- **Not done.** Social posts need an official API that is not free to read;
  the seat is where such a source would be offered if one appears. The alias
  table is short and errs toward missing a mention rather than inventing
  one. Bursts are cut by count alone; sentiment is not read.
