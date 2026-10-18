# ADR-0067 — Filling the building

Status: accepted · 2026-10-18

## Context

The operator's point about AI agents, in their own words: "a human can
think, know, learn, be good and specialize in different things, AI have a
huge knowledge but don't specialize". The idea was twenty agents, each
good at something different, balancing each other.

The company had 76 charters but seven agents forming views. The launch roster
gave each department one generalist covering everything in it:

- **INTEL** held nine charters (head, fundamental, news, sentiment, technical,
  macro, regime, alternative data, source reliability).
- **QUANT** held seven.
- **STRAT** held four.

At every seat, an agent was told the titles of everything it held, so each
read the market as a little of everything. The operator said "50-room castle,
7 people… fill it then?". The rooms had charters, and the people had not been
hired.

## Decision

**Twelve specialists are split off the generalists through the company's own
fission (ADR-0019), one charter each:**

| From | Specialists |
|---|---|
| INTEL | NEWS, SOCIAL, TECH, MACRO, ONCHAIN, FUND |
| QUANT | STAT, BACKTEST, ML |
| STRAT | ARCH |
| VALID | ROBUST |
| CRITIC | ADV |

- Fission moves the charter with its coverage, tasks and channel memberships.
  It refuses to leave a generalist with nothing, so INTEL keeps the head,
  regime and source-reliability charters, and so on.
- Each specialist goes through the M10 onboarding gate like any hire before
  it works.
- **Every seat now shows each charter's remit, not only its title.** For
  example: "News Analyst (Event detection, materiality, timeline
  reconstruction)". A specialist reads the material through what its charter
  is for.
- It is idempotent (`aurelis agent specialise`). A specialist already hired,
  or a charter no longer held by its generalist, is skipped.
- The Office draws each specialist as the figure its work suggests: the
  adversarial researcher as the hooded skeptic, the news and social analysts
  as the literature reader, the backtester and on-chain analyst at the
  workbench.

With the seven existing judges, **nineteen agents form views**.

## Consequences

- More voices at the seats and more chances to disagree, which feeds the
  huddles (M64). Each specialist starts its own forward record and its own
  evolving method (M48) from its first view.
- More agents is not assumed to be better (CLAUDE.md §16). The calibration
  machinery reports every specialist separately against a coin toss, and
  evolution rewrites the methods that lose. If a specialist adds nothing, the
  record will show it, and org development can fuse it back.
- Each wake still spends at most its call budget, so more judges spread the
  same calls over more seats rather than spending more. Making the wake
  faster is the next milestone's work.
- **Not done.** Specialists do not yet get material only they see: the news
  analyst the full headline stream, the on-chain analyst wallet flows. They
  get the same board as everyone else and differ by charter, method and the
  colleagues they ask (M64).
- **Not done.** Desks with no live feed (equities, FX, commodities, futures)
  have no hourly recordings for a view to resolve against, so specialists
  form views on crypto and memecoins only. They do read the lab's results for
  every desk (M65).
