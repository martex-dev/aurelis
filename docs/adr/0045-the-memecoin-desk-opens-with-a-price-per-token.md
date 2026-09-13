# ADR-0045 — The memecoin desk opens: a price recording per token, followed by rule

Status: accepted · 2026-09-13

## Context

M43 put a memecoin's attention on the record — paid boosts, trending
pools, posts — as events on the token, keyed by chain and contract. None
of it could be tested: a mechanism seals a prediction against a price
recording of the instrument the event fired on, and no token had one.
The operator's stated hypothesis is that a system watching social feeds
and on-chain attention can find memecoins before they run. The record
can only say whether that is true once tokens have prices.

Two facts shaped the design. A token has no exchange candle endpoint; it
has pools, and GeckoTerminal publishes each pool's OHLCV without a
credential, a thousand candles a request, thirty requests a minute. And a
memecoin worth following today is dead in a week: a grant that named
twenty tokens on the 13th would be a list of corpses by the 20th.

## Decision

### A token's bars come from its deepest pool, through the same ingestion

`GeckoTerminalCandles` satisfies the candle-feed protocol the Coinbase
adapter does. The symbol is the token key; the pool is the deepest one
the vendor lists for the token, resolved on first use and again when a
read fails. The snapshot is on the memecoin desk with the vendor as its
source, hashed like any recording, and derives the same price events. A
token's attention and its price are events on one entity.

### A dex grant names networks and a rule; the wake evaluates the rule

`aurelis service grant --source dex --network solana --network base --top 20 --days 7`
records that the service may record bars for up to twenty tokens on
those networks that the attention sources named in the last seven days,
with pool liquidity between twenty thousand and five million dollars,
newest attention first. The band is the point: below it the desk's
material size ($5,000) cannot be filled honestly, and above it the token
is not a memecoin about to be found — the first dry run's most liquid
followed token was wrapped ether on Base. The rule is printed on the
grant and parsed back from it, so the grant reads as it was written even
if the defaults move. The
person grants the class and the caps; the agents' chosen sources decide
the names; the service cannot follow a token nothing surfaced. This is
the third class grant after `news` and, in spirit, `bybit`: the
instruments on a dex grant are the networks, and the list of tokens is a
reading of the record each wake, not a column.

Each followed token's bars are recorded before settlement, so a fresh
recording settles the token's own predictions. A token with no pool is an
incident for that token; the wake goes on.

### A paper fill pays its desk's costs

The paper cycle read every fill at ten basis points of fee and five of
spread, whatever the desk. It now reads the desk's own cost model:
commission, spread and impact, so a memecoin fill pays thirty, a hundred
and fifty and two hundred, and the version a mechanism trades under
declares the same numbers. The desk that sets the cost is the
*instrument's* — the desk of its newest recording — not the version's: a
crypto-desk mechanism whose event fires on a token (the second dry wake
sealed twenty-nine predictions, many on tokens, for the three crypto
mechanisms) is filled on that token at the memecoin desk's costs. The
crypto desk's own fills pay a little more than before (impact was not
charged); the scheme test's edge still clears it. An instrument with no
recording pays its version's desk; a desk with no model pays the crypto
desk's.

### A mechanism is stated on the desk its pattern fired on

The discovery seat stated every mechanism on the crypto desk. The desk is
now read from the newest recording of the instrument the pattern was
found on, and only a pattern on an instrument with no recording falls
back to the caller's desk. A mechanism on `attention.boost` found on a
Solana token is a memecoin mechanism, trades in the memecoin book, and
pays the memecoin costs.

### Bluesky refuses some cashtags; the name is tried next

The app view answers `$BTC` and refuses `$ETH`, `$DOGE`, `$ADA`, `$XRP`
outright ("forbidden by administrative rules"), consistently, not as a
rate limit. A per-instrument reader is given every search worth trying,
cashtag first and then each name the alias table knows, and moves to the
next on a refusal; only an instrument every search failed for is named
in the wake's note.

### Social readers search a token by its ticker

A cashtag search for a contract address finds nothing. The wake passes
the followed tokens' tickers, from the entity the attention source saw,
and a per-instrument reader searches `$WIF`; a token nobody has named is
skipped and the wake says so.

## Consequences

- The memecoin desk's instruments have no aliases in the headline
  matcher; a headline about a token matches nothing until an alias table
  for tokens exists, and posts reach the token only through the cashtag
  search.
- Twenty tokens at hourly bars is twenty pool lookups once and twenty
  OHLCV requests a wake, paced at two seconds each with one wait on a
  429: under two minutes, inside the vendor's thirty a minute. The first
  dry wake paced only the candle reads and was refused on six of eight.
- A mechanism stated on the crypto desk is tested wherever its event
  fires, tokens included, as M34 decided; its predictions on tokens are
  scored against the token's close and its fills there pay the token's
  costs.
- The judges' seat now offers tokens as instruments to state views on,
  with their attention events in the material.
- **Not done.** The desk is not formally *opened* through the M12
  checklist; its cost model, calendar and limits exist and are used, and
  the checklist's data item would read the same provisional state it
  reads for every desk. Nothing weighs a token's liquidity against the
  desk's material size when a paper position is sized. Pool OHLCV is in
  USD via the quote token; a pool quoted in a token that itself moves is
  read as the vendor converts it.
