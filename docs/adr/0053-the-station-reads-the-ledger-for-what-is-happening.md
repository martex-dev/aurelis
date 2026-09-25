# ADR-0053 — The station reads the ledger for what is happening

Status: accepted · 2026-09-25

## Context

The operator sent a screenshot of the facility with every room IDLE and
wrote: "the station is broken all the time it stays like that no one working
nothing new." At that moment the agents were sealing more than twenty views an
hour.

The station was not broken. It was measuring the wrong thing. Room plates and
the figures in them were read off `agents.state`. The service's seats never
set that column: a seat claims a task, calls the model and seals a view in
one transaction, so any page read finds the agent idle again. Everything the
company did was in the ledger, and the facility never read it. The brief asks
that the user can operate and understand the whole system through Mission
Control. A building that always reads IDLE fails that, however true each of
its numbers is.

## Decision

- **Activity comes from the ledger** (`station/activity.py`). An agent is
  working if an event with its ref as actor was recorded in the last ten
  minutes. A room is working if one of its agents is, and only that many
  figures move. Each room also shows how long ago it last acted and how many
  acts it recorded in the last hour. A meeting still reads off the agent
  state, since a meeting holds its agents for its whole length.
- **The current wake.** `service.woke` is appended when a wake ends. Any
  recordings or model calls after the last one are the next wake, under way.
  The facility says so, with the wake's model calls and decisions so far,
  and otherwise shows the last wake's note.
- **Today's counts**, since midnight UTC: views sealed, scored, declined and
  refused; brain notes; model calls; social posts read; mechanism
  predictions; paper fills; alerts.
- **Who is doing what.** A row per agent: whether it is working, when it last
  acted, the plain line of that act, and its last hour in words.
- **A live feed.** Every decision is shown as a line built from the event's
  own payload, never paraphrased, newest first. Recordings and model calls
  are counted, not listed. The page's existing server-sent-event stream now
  carries each event's line, and new lines appear as they are recorded.
- **Refreshed in place.** `/now` serves the changing part of the facility
  alone, and the page swaps it in every fifteen seconds.
- **A coin toss is a free figure.** "0.5" and "50%" name the yardstick every
  view is scored against. Two live refusals after M51 were an agent saying
  its call was no better than 0.5.

## Consequences

- The building reads what the company is actually doing. The idle rooms
  (Executive, Audit, Knowledge, Infrastructure) are idle in the record too:
  those agents have not acted. They are shown as idle, not hidden.
- A wake stamps each decision with the moment it woke, which is the as-of
  time a view is sealed against. So a decision can read older than the model
  call that made it. The page says so rather than rewrite the stamp.
- The facility costs a handful of indexed queries per refresh. At one
  refresh per fifteen seconds per open page, that is negligible next to the
  service.
