# ADR-0051 — The company follows social media through the operator's device

Status: accepted · 2026-09-25

## Context

The operator's hypothesis is that memecoins about to be hyped can be caught
by watching where attention forms: Telegram call channels, X, Discord and
Reddit. Until now the catalogue held only sources a vendor issues free
through an official API. That left out most of where memecoin attention
lives:

- X's free API tier cannot read posts.
- Telegram and Discord have no keyless read API for public channels.
- Reddit's OAuth API now needs an app that Reddit must approve first. The
  operator applied, and approval can take days or be refused.

The operator was told the risks: account bans, the platforms' terms, and
prompt injection from shill posts. The operator answered that they accept
the ban risk and have no objection to scraping, and asked that the agents
use X, Discord, Telegram and Reddit "smartly through my device".

## Decision

**The agents decide what is read, and deterministic code reads it.** No
model drives a browser or an account. Each reader is read-only by
construction:

- it fetches only URLs it builds from a validated handle (a channel name, a
  subreddit list, an account name);
- it never follows a link a post contains;
- it has no code path that clicks, posts, reacts, joins or sends.

A post reaches the company only as data: text in a world event. It is read by
agents under the brain's rule that notes and posts are opinions, not
evidence. Whatever a shill message says, it cannot make anything act.

M50 ships what needs nothing from the operator:

- **Reddit without an app.** Reddit's logged-out JSON now redirects to a
  login page. Its Atom feed, `www.reddit.com/r/<subs>/new/.rss`, still
  answers with the newest 25 posts. There are two sources: `reddit_web_crypto`
  and `reddit_web_memecoins`. A redirect to the login page is a failure,
  never an empty feed.
- **Telegram public channels** (`telegram_channels`) through Telegram's own
  web preview, `t.me/s/<channel>`. It gives each message's text, time and
  view count with no account. A group has no preview and says so.
- **Social targets.** A follow or drop of one handle on one platform is an
  append-only row, `SOC-`, with who decided and why. The newest decision
  wins. Targets come from three places:
  - **token links**: each memecoin followed on the dex desk publishes its own
    X account and Telegram channel on DEX Screener, and the company follows
    them while it follows the token, landing their posts on that token;
  - **the operator**: `aurelis social follow|drop|list`;
  - **an agent**: the table takes `decided_by`, and agent curation comes in M51.
  A drop overrides a token's link.
- **Cashtags count.** The text matcher refused any ticker after a `$`. That
  rule dates from headline matching in M41, and no reason was recorded. So
  `$BTC` and `$MOON`, the way crypto posts name coins, were never matched. A
  cashtag now names its coin, even a ticker that is also an English word
  (`$ONE`). A memecoin, keyed by chain and contract, is matched by its
  ticker's cashtag only, because its bare ticker is too often a word ("MOON").

M51 adds what needs the operator's sign-in once: X and Discord, read through
a dedicated browser profile the operator logs into, under the same read-only
construction. It also lets the agents curate targets by their measured lead
over price.

## Consequences

- The catalogue is no longer "official APIs only". Two kinds, `reddit_web`
  and `telegram`, read what the platforms serve to any visitor, at the
  operator's direction. `KINDS` says so, and the catalogue test pins it.
- Every post still carries its source, its URL and the fetch's raw artifact.
  A burst on a token can be traced to the channel messages that made it.
- Telegram groups, private channels and Discord servers the operator is not
  in cannot be read. The wake names each channel it could not read.
- The account-ban risk the operator accepted applies to M51's signed-in
  readers. M50's readers use no account.
