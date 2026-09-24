# ADR-0047 — The shared brain: one memory every agent reads, and can add to

Status: accepted · 2026-09-24

## Context

The operator asked for all the agents to share one central brain, kept in
Obsidian.

Through M45 each agent at a seat saw its own record and nothing else: its
own calibration and its last five scored views. What the others had
concluded reached nobody. Nine agents declined `book.snapshot` pairs
thirty-five times in one morning, each for the same reason, each paying for
the call. A mechanism was retired as noise and nothing stopped the next
agent restating it. The operator's hypothesis about memecoins had no way into
the room at all. The existing Obsidian export (M8) rendered only the old
strategy corpus, was write-only, and no agent ever read it.

Two constraints from the charter shaped the answer. The database is the
record, and the knowledge layer must not depend on Obsidian (CLAUDE.md §15).
And a seat has no tools (ADR-0024): an agent cannot open a file, so whatever
it shares has to arrive in its prompt.

## Decision

### The brain is a briefing every seat carries

Every seat's system prompt now carries the brain after the agent's identity:
the judgement seat, the discovery seat and the sources seat. It has two parts.

The **record** is derived from the database on every read: the mechanisms
under test and their state, the agents' own calibration against a coin toss,
the paper book, the retired mechanisms and why, and the patterns most
declined with one reason each. Most important first, so a cut for length
loses the least. Its figures are the record's, so the figure guard accepts
them. It is cached until the record it reads changes. Built from the live
workspace it is about 625 tokens.

The **notes** are what agents and the operator left for the company, newest
first, the operator's ahead of equals, and on the seat's topic first. They
are opinions: the figure guard does not accept a number that appears only
in a note. A judge sitting on an instrument also sees the notes on that
instrument beside its material; a discoverer sees the notes on the two event
kinds it is shown.

### An agent writes to the brain with one optional line

Each reply form gains an optional `NOTE:` line: one or two sentences every
other agent should know from what this agent just saw. It is available when
stating a view, declining a view, stating a mechanism and declining one. The
note is recorded with its author, time, topics (the instrument, the event
kinds, the mechanism) and the thesis or mechanism it came with. A note citing
a figure the agent was not shown is dropped; the reply it came with stands.
The same author writing the same words twice is one note. Notes are
append-only by trigger, because every agent that sat afterwards was shown them.

### The operator writes to the brain through Obsidian

Every wake renders the brain as an Obsidian vault in `<workspace>/brain`:
`Home` holds the record and notes exactly as agents read them, with a page
per mechanism, agent, note and instrument, all linked, plus a page of
declines and a journal per day of what the service did. Pages whose content
did not change are not rewritten, so Obsidian does not reload every hour.

The vault is a view and every generated page says so. The one way in is
`Inbox`: a Markdown file dropped there is read by the next wake into the brain
as a note from the operator, with its `[[links]]` and `#tags` as its topics,
and moved to `Inbox/Read` with the note's ref in its name. `aurelis brain
note "..."` does the same from a terminal. An operator note has an author and
a time like everything else, and it is weighed as an opinion, not cited as a
measurement.

### Where it can be read

`aurelis brain show` prints the brain as a seat reads it, `aurelis brain
notes` lists the notes, and `aurelis brain export` renders the vault on
demand. The station has a `/brain` page.

## Consequences

- Every seat call carries about 625 more tokens. At 400 calls a day that is
  under a quarter of a million input tokens, and it is the price of agents
  that can hear each other.
- The model-response cache hits less often, because the brain changes as the
  record does. Identical questions against an identical record still hit.
- The memory of the company is now load-bearing. An agent that restates a
  retired mechanism does so against a line telling it why that mechanism
  died.
- **Not done.** Notes are not scored: nothing yet measures whether an agent's
  notes were useful to the agents that read them. Nothing summarises old notes
  when there are too many; the newest win the budget. The critic's seat does
  not read the brain yet. Agents cannot search the vault; they see only the
  briefing.
