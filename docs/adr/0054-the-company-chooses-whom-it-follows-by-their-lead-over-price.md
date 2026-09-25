# ADR-0054 — The company chooses whom it follows by their lead over price

Status: accepted · 2026-09-25

## Context

M50 and M51 gave the company Telegram channels, X accounts and Discord
channels. A handle was followed for one of two reasons: a followed memecoin
linked it on DEX Screener, or the operator typed it. The table has taken an
agent's decision since M50, and ADR-0052 left "the curation seat is next".
Nobody measured whether a voice was worth reading.

The operator's hypothesis is that attention forms before a price moves. That
is a claim about particular voices, and it can be checked against recordings
the company already keeps. The cashtag searches also show the company
hundreds of X accounts it does not follow. Some of them may be early. Most
will be accounts that post about a token after it has already pumped.

## Decision

### A voice's record is measured in software

A **voice** is a handle the company could follow: an X post's author,
whether it was read on the author's timeline or in a cashtag search; a
Telegram channel; or a Discord channel. Reddit, Bluesky and Stocktwits posts
are not voices, because the company has no handle to follow there.

For every post a voice made about an instrument whose prices are recorded,
`social/voices.py` measures:

- **The move after.** The instrument's return over the next 24 hours, less
  the median return of the other instruments on its desk over the same
  hours. A post on a day everything rose is not a call. At least three peers
  must be priced.
- **The move before.** The same measure over the 24 hours before the post. A
  voice that posts after the move is a chaser.

Prices are the closes of the bars each end falls inside, read from the
recordings as of the moment measured. A move inside the bar a post was made
in may have come before the post, so it counts as the move before and is
never credited as a lead. A bar that was still open when it was fetched is
not a close. A missing bar means the price is unknown; it is not replaced by
the last price seen. An episode whose 24 hours have not been recorded yet is
pending, not a miss.

Posts are counted by **independent episode** (ADR-0040). A voice's post
starts an episode, and anything it posts within 24 hours of that start joins
the same episode, on any instrument. The episode's move is the mean over its
instruments. A record is read only from ten episodes.

### The bar is divided by how many voices were measured

A voice **leads price** when its episodes were ahead of their peers more
often than a coin would be, by an exact one-sided sign test at
`0.05 / (voices with ten or more episodes)`. It **trails price** when the
same test finds its instruments had already beaten their peers before it
posted. The sign test ignores how large each move was, so one memecoin that
tripled cannot carry a voice alone. The bar is divided by the number of
voices measured because showing an agent the best of forty records is a
search: the best of forty coins looks lucky.

### An agent chooses, from a closed set, once a day

Once a day, under the news grant, a market-intelligence agent sits the
curation seat. The seat goes to the agent who has gone longest without
sitting it. It sees how voices are measured, the bar, and two lists:

- **You may follow.** Voices the company does not follow that have at least
  ten episodes, were ahead more often than not, and do not trail price. The
  fifteen strongest records are shown.
- **You may drop.** Followed voices that have at least ten episodes and do
  not lead price.

The agent replies `FOLLOW`, `DROP` and `BECAUSE`, with at most three follows.
A reply that names anything outside the two lists is refused (ADR-0015). The
choice is the agent's. It may keep everything, and a record that clears the
point estimate but not the bar is its call to make with the bar in front of
it. Each follow or drop is a `SOC-` row by the agent, with its reason and the
record as it stood. A voice that leads price cannot be dropped by an agent,
and a voice still gathering cannot be followed or dropped by one. The
operator's `aurelis social follow|drop` is unchanged.

### Every sitting is on the record

Each sitting is a `social.curated` event, including a refused reply and a day
on which nothing was eligible. The event lists what was offered, what was
decided and why, and the digest of the full record stored as an artifact.
When nothing is eligible, no agent is asked and no model call is made.

### After a follow, only the episodes since count

A followed voice's record splits at its latest follow. The episodes before
it are the ones it was chosen on. The episodes after it are the only ones
nobody selected it on. The station, the CLI and the seat all show them apart.

## Consequences

- `aurelis social voices` and the station's `/voices` page show every voice's
  record and every sitting.
- A token's own X account and Telegram channel are measured like any other
  voice. If they only ever post after their token has moved, the record will
  show it, and an agent may drop them. A drop overrides the token link, as
  in M50.
- The curation costs at most one model call a day. The measurement is a
  handful of indexed queries per instrument.
- **Not done.** The 24-hour horizon is fixed. A memecoin's hype may lead by
  minutes, not hours, and measuring several horizons would multiply the
  family the bar is divided by. Voices are not yet weighted by how often
  they post, so a voice with 200 posts and one with ten are both one record.
  Telegram channels and Discord channels the company does not follow are
  never met, because nothing reads them. Discovering those needs a reader
  that follows links, which ADR-0051 rules out.
