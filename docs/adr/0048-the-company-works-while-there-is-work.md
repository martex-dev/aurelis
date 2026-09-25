# ADR-0048 — The company works while there is work, and asks about what is rare

Status: accepted · 2026-09-25

## Context

The first two wakes after M46 spent 20 and 15 of their 400 model calls and
stopped with "every action that could move an unmet condition is exhausted".
The operator had just raised the budget and wanted the company to use it.
More budget would have changed nothing, because the work queue was starved
by four rules:

1. **A decline blocked every market.** After an agent declined or was refused
   on one instrument, it was not seated again, on any of the 67 instruments,
   until the next hourly recording. A refusal also did not say which
   instrument it was about, so it could not be narrowed.
2. **Mechanism predictions counted as views.** A mechanism's predictions carry
   its author's ref. LEAD-R appeared to hold 32 open views, but they were
   predictions of mechanisms it had stated.
3. **The miner offered noise.** Pairs were ranked by count, and the top eight
   were always hourly price and flow events, which co-occur with everything.
   Individual social posts, the most common event of all, dominated. The
   operator's hypothesis lives in rare events: a paid boost, a burst of posts,
   a headline burst. None of them made the list.
4. **The same pairs were re-asked every hour.** An answer stood only until any
   new world event, and one arrives every wake, so the same agents declined
   the same patterns each hour for the same reasons.

The miner also took 7.5 seconds, and the loop ran it on every cycle.

## Decision

- **Declines are remembered per market.** A decline or refusal on an
  instrument keeps that instrument away from that agent until the instrument
  has a new recording. The agent is still offered the other markets. A
  refusal after a market was picked names it. Declining to pick any market
  keeps the agent waiting for the next recording, as before.
- **A mechanism's predictions are not its author's views.** They no longer
  block the author from forming its own view on those instruments.
- **The miner counts every pair in one pass**, cached until the event stream
  changes. Counts match the old pair-by-pair method, and the time drops from
  7.5 seconds to 0.1. The loop now uses `mine_diverse`: each trigger kind
  brings its two strongest partners, rarest trigger first, up to 24 pairs.
  `social.post` joins the readings: a single post is the stream, and
  `social.burst` is the event.
- **A pattern is re-asked only on real new evidence.** A decline records how
  often the pattern had occurred. The pattern goes back to that agent only
  once it has occurred at least 1.5 times as often.
- **A wake takes its share of the day.** `--calls-per-wake` caps a single wake,
  so a large daily budget is spread across the day rather than spent by the
  first wake. `--cycles` sets how many actions a wake may take. The supervisor
  now runs 1,200 calls a day, at most 100 per wake, and up to 150 actions per
  wake.

## Consequences

- On a copy of the live record, the loop had 140 pattern questions to put to
  agents instead of none. Social bursts, news bursts and trending pools reach
  the agents for the first time.
- Six of seven judges declined to pick any market on the latest recordings.
  That abstention is legitimate and is recorded as such. They are asked again
  at the next recording.
- **Not done.** The judge seat still shows every instrument at once. An agent
  cannot yet ask to see one market in more depth before deciding.
