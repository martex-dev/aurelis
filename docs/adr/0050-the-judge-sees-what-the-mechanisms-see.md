# ADR-0050 — The judge sees what the mechanisms see

Status: accepted · 2026-09-25

## Context

M48 fixed the figure guard. After that the live judges stopped being refused
and started giving reasons, and five of seven gave the same one in their own
words on the first M48 wake:

> The mechanisms actually beating the drift in the record (MEC-0006,
> MEC-0007) depend on book/flow reads I don't have here.

They were right. The first question a judge answers, which market to state a
view on, showed one line per market: the close and four price changes. The
mechanisms that beat the drift key off a range break, a bid-heavy book or
one-sided taker flow. The service records all of these every wake, but none
of them appeared at the market stage. The view stage showed eight recent
events for the one market picked, but an agent had to pick blind to get
there. So it declined.

A company whose analysts cannot see what its own research says works is not
using its research.

## Decision

- **A market board** (`judgement/board.py`) adds three things to each
  market's line at the market stage:
  - **readings**: the newest book bid share, taker buy share, annualised
    funding and 24-hour open-interest change, if the reading is under three
    hours old;
  - **signals**: the event kinds that fired on the instrument in the last day,
    newest first, up to five, each with its defining figure and how long ago;
  - **open mechanism calls**: the unresolved predictions a mechanism has
    sealed on the instrument, with direction and resolution time.
- **The board is as of what the company knew.** Events count by
  `recorded_at <= now`, and only predictions sealed by now appear. A judge is
  never shown something the company learned after the moment it is judging.
- **The view stage shows the picked market's board in full** beside its
  closes and recent events.
- It is material, not advice. A mechanism's call is evidence the agent may
  use or argue against. The agent's view is still its own and is scored on
  its own, and a view that merely copies a mechanism earns the mechanism's
  calibration, not a better one.
- **A clock time is not a figure.** The guard no longer reads the `09` and
  `30` of `09:30` as numbers. One live refusal after M48 was exactly that.

### After the first M49 wake

The first wake on M49 used its full 100-call budget and sealed 19 views, up
from 5. It also left 19 brain notes. It showed two more things:

- **A zero-padded integer is a name.** Two refusals cited `0004` and `0007`,
  from shorthand such as `MEC-0004/0007`. Nobody writes a measurement with
  leading zeros, so the guard no longer treats one as a figure.
- **GeckoTerminal's free limit is about five requests a minute.** It is not
  the documented thirty. Twenty requests three seconds apart from the live
  machine returned four 200s, then twelve 429s, then two 200s at the minute's
  end. The wake had recorded 4 of 20 followed tokens. Every GeckoTerminal
  reader now shares a 13-second pace (`GECKO_PACE`). With pools cached after
  the first wake, twenty tokens take about four minutes of an hourly wake.

- **Bluesky reads in full with an optional sign-in.** The same wake lost 26
  of 50 Bluesky searches to a 403 ("Request forbidden by administrative
  rules"). Anonymous search is partly refused by query: "bitcoin" answered
  and "arbitrum" did not. A source may now name optional keys. With
  `AURELIS_KEY_BLUESKY_HANDLE` and `AURELIS_KEY_BLUESKY_APP_PASSWORD` set,
  the reader opens one session through the official `createSession` and
  searches signed in, renewing an expired session once. Without them it
  searches anonymously as before. Creating the account is a person's step.

## Consequences

- The market stage grows by about 6,000 tokens on the live record: 69
  markets, 52 with a board. That is within the per-wake budget. The option
  list itself keeps the short price summary, so the board is not shown twice.
- Judges can now form views that synthesise mechanisms. That is the
  "Strategy Synthesizer" role the brief describes, arrived at by the agents'
  own request rather than by a new role.
- **Not done.** The board does not show a mechanism's calibration next to
  its call. The brain shows it once, above the board, and repeating it per
  line would cost more than it adds. Memecoin tokens have no book or flow
  readings: their board is signals and calls only.
