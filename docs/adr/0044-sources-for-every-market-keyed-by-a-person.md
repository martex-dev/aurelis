# ADR-0044 — Sources for every market, chosen by the agents, keyed by a person

Status: accepted · 2026-09-13

## Context

M41 gave the agents a catalogue of four crypto publishers' RSS feeds and
the seat in which to ask for them. The operator's instruction on the 13th
widened the scope on three axes at once: the agents should decide what
news and social media they need *for every market*; the sources must stay
free; and where a free source needs a key, the operator will supply it.
The operator also said where they think the opportunity is — memecoins
about to be hyped, watched through social feeds — which is a hypothesis
for the record to test, not an assumption for the code to make.

Two things fixed the shape of the catalogue before any code. First, the
project's rule since the brief: official interfaces only, no scraping,
nothing that gets the company banned. Second, what actually answers on
those terms. Probed on the 13th: DEX Screener's boost and token endpoints,
GeckoTerminal's trending pools, Stocktwits' symbol streams and Bluesky's
post search answer without a credential; Reddit's public JSON is blocked
and its official API wants an app's credentials; CryptoPanic's developer
API wants a token; publishers' feeds for the other markets (SEC, the Fed,
the Bank of England, EIA, CNBC, MarketWatch, Yahoo Finance, OilPrice,
FXStreet) answer. X's free tier cannot read posts. Telegram channels are
readable only as a person's own account.

## Decision

### Free means free, not keyless; a key is a person's, in the environment

A source may declare the environment variables it needs, all prefixed
`AURELIS_KEY_`. The catalogue knows whether each is *set*, never its
value; readers read the value at fetch time and put it in the request
only. `aurelis source keys` lists the variables and whether each is set.
A keyed source's status is shown to the agent, who may ask for it anyway;
the wake reads it once the key is there and, until then, notes which
variable is missing — a note for a person, not an incident.

### Every source names its markets, and the seat shows instruments per desk

Each source carries the desks it bears on. The seat shows the catalogue
with markets and key status, and the instruments the company follows
grouped by desk, and asks the agent to choose for every market it follows.
Nothing pre-assigns a source to a desk; the agent's reasons are the
assignment, on the record.

### Four kinds of reader beyond RSS, one dispatch

`stocktwits` and `bluesky` read per followed instrument and land
`social.post` on it, with the poster's own bullish/bearish tag where the
platform has one, never a sentiment inferred here. `reddit` reads a
subreddit listing with the app's OAuth token and matches posts to
instruments by text. `cryptopanic` reads the developer API as headlines.
`dexscreener` lands `attention.boost` on the token, once per total paid,
with the token's symbol, liquidity and market cap from the lookup.
`geckoterminal` lands `dex.trending` on the token, once a day a pool
enters the list. Boosts and trending are events, not readings: a token
still on a list is not a new event, a token boosted again is. The fetch
happens outside a database session and the record inside one, because a
reader that makes thirty requests must not hold the file lock for them.

One burst rule (`aurelis.intel.bursts`) serves headlines and posts alike:
at least three events in six hours and at least three times the trailing
week's six-hour rate, threshold in the event. A rate needs history: with
no event older than six hours the rate is unknown, not zero, and nothing
bursts against an unknown rate. The first dry wake on a copy of the live
workspace, before that clause, derived a burst on every one of thirty
instruments from their first reading.

A source read per instrument fails per instrument. Stocktwits does not
list one of the thirty symbols and Bluesky refused three of thirty
queries on the dry run; each is named in the wake's note against the
instrument, the other instruments are recorded, and only a source that
failed on every instrument is an incident.

### A token is an instrument, keyed by chain and contract

A boosted or trending token is the instrument `<chain>:<address>`, seen
with its symbol. The key is the one a price recording of the token's pool
will use, so its attention and its price are events on one entity and the
miner can join them. No price recording exists yet, so no mechanism can
seal a prediction on a token; the events accumulate so that when the
memecoin desk opens with a per-token price feed (the next milestone), the
attention that preceded each move is already on the record, at its own
time.

## Consequences

- The wake's note reads `sources: N read, M event(s), B burst(s)`; the
  M41 wording changed with it.
- The mandate's `sourced` reading names keys not yet supplied, and is not
  met while every requested source waits on one.
- The catalogue digest changed, so every market-intelligence agent is
  asked again on the next loop: one call each.
- Stocktwits and Bluesky cost one request per followed instrument per
  wake — sixty requests for thirty instruments — inside both platforms'
  published limits at an hourly wake, and reconsidered before the wake is
  made more frequent.
- **Not done.** No feed reads X or Telegram, for the reasons above. No
  sentiment is inferred from text; only the poster's own tag is recorded.
  Reddit and CryptoPanic readers are built to the vendors' documentation
  and exercised against recorded payloads; they have not been run against
  the live endpoints, which needs a key the operator holds. Instruments on
  desks other than crypto have no aliases yet, so a headline about crude
  matches no instrument until the desk that follows crude opens.
