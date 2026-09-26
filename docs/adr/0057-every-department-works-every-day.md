# ADR-0057 — Every department works, every day

Status: accepted · 2026-09-25

## Context

The operator asked for every agent to be on its role and working around the
clock: analysing, thinking, communicating, evolving and trading on their own.
The service already wakes every hour, day and night. Measured against the
roster, though, most of the company had nothing to do:

- The wake seats the judging departments (Market Intelligence, Quantitative
  Research, Strategy Lab), the source and curation analysts, and, when a
  scheme trades, Risk, the Portfolio Manager and Trading.
- The CEO, the research director (CIO), the Operations Director, the auditor,
  the governance officer, the knowledge agent and the infrastructure agent
  had no duty in it at all. Seven of the seventeen launch agents never acted.
  M52's station showed their rooms idle, and the record agreed.

Two of the research actions also stopped for good at their first success.
`judge` ran only while `calibrated` was unmet, and `discover` only while
`scheme` was unmet. So the forward record stopped growing on the day the
agents first beat a coin toss, and the hunt for new mechanisms stopped on the
day MEC-0001 became a candidate scheme. A company that stops researching
because it once succeeded is not working around the clock.

## Decision

### Judging and discovery are standing duties

They run whenever they have work, like choosing sources since M53. Their
exhaustion rules are unchanged: a judge is not reseated on a market it holds a
view on or declined on the standing recordings, and a pattern is not put to an
agent again until it has grown half as frequent again. What changed is that
they no longer stop at the first success. Choosing sources stays first among
the standing duties, so a changed catalogue is still asked about before
anything else.

### Every department holds a daily duty

`autonomy/duties.py` gives each idle department one duty, run once a day by
the agent whose charter it is, or by anyone active in the department if that
agent has been split:

| Duty | Held by | What it does | Model calls |
|---|---|---|---|
| audit | the auditor | verifies the ledger chain; flags paper round trips held past their horizon; flags agents with at least four replies in the day, most of them refused | 0 |
| integrity | the governance officer | re-hashes every mechanism's seal, the day's view seals and the day's recordings | 0 |
| health | infrastructure | counts the day's wakes, the longest gap between them, model calls and open alerts | 0 |
| lessons | knowledge | writes one lesson from what the day retired, suspended, scored worst and dropped | 1, only if something closed |
| memo | the research director | writes a short memo from the record, the mandate, the day's counts and the other duties' findings | 1, only if something happened |

Each duty changes real state. Each problem the checks find is an alert,
raised by the agent that holds the check's alert scope. A lesson is a row in
the company's lesson record, citing what it came from, and a note in the
shared brain. The memo is a note in the shared brain. Every seat reads the
brain, so the research director's memo reaches every agent until the next
one. A lesson or memo that cites a figure the agent was not shown is
withheld, as at every seat.

The checks run first, so the memo can read what they found. Every run is an
`org.duty_done` event with the holding agent as its actor, so the station
lights that agent's room from the work itself. A duty that raises is
recorded as done with the error, and waits a day like the others rather than
failing every wake.

### No duty is invented work

A duty that would only produce text nobody reads was left out. There is no
daily CEO speech and no stand-up meeting between agents with nothing new to
say. CLAUDE.md asks that meetings not become roleplay, and a duty is held to
the same rule. Each of the five either checks something that can fail or
writes something every seat then reads.

## Consequences

- On a normal day the company spends at most two more model calls, and the
  three checks cost nothing.
- The auditor, the governance officer, infrastructure, knowledge and the
  research director act every day, with their findings on the record. The CEO
  and the Operations Director still act only through the chains they already
  sit in. Operations raises the service's incidents.
- `aurelis duty list` shows each duty, who holds it and when it last ran.
  `aurelis duty run` runs the due ones now.
- **Not done.** The memo directs attention in words; nothing yet turns it
  into a change to the agenda's order or the day's budget. That would be the
  executive deciding what the company works on, and it should be measured
  like any other organisational change (ADR-0012) before it is allowed.
