# 06 — Mission Control Station

Date: 2026-09-04
Status: proposal, v2.

Mission Control is the primary human interface to the company. The target is
literal: **you should be able to run and understand Aurelis without opening a
terminal, a source file, a log, or an agent transcript in raw form.**

It is not a dashboard bolted onto a backend. It is the building the company
works in, and every room in it is backed by real state.

---

## 1. The two rules

**1. The station draws the record, never the design.**

If a number is not in the database, the station shows nothing and says why —
`NO DATA`, in the same words the underlying record uses. Every exit from every
pipeline is drawn at its true size, including the ones that read zero. A room
for a department that has done nothing shows an idle room, not a busy one.

**2. Every figure names its source.**

The `Figure` type has no constructor that omits `source`. A number cannot reach
the screen without naming the artifact, table or run it was read from, and
clicking it opens that source. This is what makes "nothing on this page was
typed" a checkable property rather than a promise.

A corollary: **the station computes no verdicts.** A station that derived its
own conclusions would become a second, unversioned source of truth competing
with the record.

---

## 2. Visual direction

As specified in `CLAUDE.md` §20:

- pixel-art-inspired, industrial research facility
- dark sci-fi, mechanical infrastructure, laboratory atmosphere
- dense but organized; highly readable
- game-like without being childish
- subtle futuristic technology

Avoided: generic SaaS dashboards, glassmorphism, neon cyberpunk, gradient
soup, visual clutter.

**Vector only. No binary assets.** Every wall, lamp, console, pipe and figure
is generated geometry — which keeps the page diffable, the build reproducible,
and the whole facility drawable from configuration rather than from art files.

Geometry is **generated, not hand-placed**: rooms lay out from the department
and desk registries, furniture is placed by a hash of the room's own id, so two
builds of the same state produce the same picture. Every text label is measured
and a test asserts that no two label boxes overlap.

---

## 3. The facility

```
╔══════════════════════════════════════════════════════════════════════════╗
║  AURELIS · MISSION 047 · 3 ACTIVE DESKS · 28 AGENTS · ▲2 ALERTS · $4.10  ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                ║
║   │  EXECUTIVE   │───│   MARKET     │───│ QUANTITATIVE │                ║
║   │ MISSION CTRL │   │ INTELLIGENCE │   │   RESEARCH   │                ║
║   │  ● WORKING   │   │  ● WORKING   │   │  ● WORKING   │                ║
║   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                ║
║          │      ═══ service deck ═══           │                        ║
║   ┌──────┴───────┐   ┌──────────────┐   ┌──────┴───────┐                ║
║   │   STRATEGY   │───│  PORTFOLIO   │───│   TRADING    │                ║
║   │  LABORATORY  │   │   & RISK     │   │  OPERATIONS  │                ║
║   │  ● DEBATE    │   │  ○ IDLE      │   │  ● PAPER     │                ║
║   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                ║
║          │                  │                  │                        ║
║   ┌──────┴───────┐   ┌──────┴───────┐   ┌──────┴───────┐                ║
║   │    AUDIT     │   │  KNOWLEDGE   │   │INFRASTRUCTURE│                ║
║   │ & GOVERNANCE │   │  & MEMORY    │   │              │                ║
║   │  ● SAMPLING  │   │  ● INDEXING  │   │  ● HEALTHY   │                ║
║   └──────────────┘   └──────────────┘   └──────────────┘                ║
║                                                                          ║
║   ┌──────────────┐                    ┌──────────────┐                  ║
║   │ THE REGISTRY │  (no corridor)     │  THE VAULT   │  (no corridor)   ║
║   │  governance  │                    │ sealed data  │                  ║
║   └──────────────┘                    └──────────────┘                  ║
║                                                                          ║
║   ┌────────────────────────────────────────────────────────────────┐    ║
║   │ THE FLOOR — desks: CRYPTO ● │ EQUITIES ● │ OPTIONS ○ │ FX ○     │    ║
║   └────────────────────────────────────────────────────────────────┘    ║
║                                                                          ║
║   ┌────────────────────────────────────────────────────────────────┐    ║
║   │ THE GRAVEYARD — 172 refuted · 41 inconclusive · browse          │    ║
║   └────────────────────────────────────────────────────────────────┘    ║
╠══════════════════════════════════════════════════════════════════════════╣
║  TIMELINE  ◀ 09:31 E-501 completed · 09:34 Critic challenged · 09:42 ... ║
╚══════════════════════════════════════════════════════════════════════════╝
```

Rooms are drawn as **cutaways** — chambers seen from the side, with ceiling,
back wall and floor, agents standing at their stations, and the plant that runs
the building between them: a service deck, trunk lines, and a hall of tanks
underneath. None of the plant carries a number, because none of it records
anything.

**The rooms are laid out from the department and desk registries**, not beside
them. A department that exists has a room; a desk that opens gets a bay on the
floor; a state of the research machine is owned by exactly one room. A test
asserts that every role is stationed somewhere and every state is owned.

**Two rooms have no corridor** — the Registry (where preregistrations lock) and
the Vault (where the Custodian holds sealed data). You cannot walk into them,
which is the honest picture of a process boundary.

At rest, a room shows only its status plate: `WORKING` · `IN MEETING` ·
`IDLE` · `BLOCKED` · `NO DATA`. Hover for identity, click to enter, press
`labels` to put every caption and roster back on.

Drag to pan, scroll to zoom.

---

## 4. Drill-down

Everything is clickable, and every path terminates in an artifact hash.

```
COMPANY
 ├── MISSIONS ──▶ mission ──▶ project ──▶ task ──▶ artifact
 ├── DEPARTMENT ──▶ teams ──▶ agents ──▶ agent detail
 ├── DESK ──▶ instruments · data health · strategies · research · P&L (paper)
 ├── MEETINGS ──▶ meeting ──▶ transcript ──▶ turn ──▶ cited evidence
 ├── RESEARCH ──▶ hypothesis ──▶ registration ──▶ experiment ──▶ run ──▶ artifact
 ├── STRATEGIES ──▶ strategy ──▶ version ──▶ gates ──▶ evidence ──▶ paper record
 ├── PORTFOLIO ──▶ allocations · exposures · correlations · capacity
 ├── RISK ──▶ limits · assessments · vetoes · halts · kill state
 ├── TRADING ──▶ proposals ──▶ approvals ──▶ orders ──▶ fills ──▶ post-trade
 ├── KNOWLEDGE ──▶ graph · claims by confidence · lessons · GRAVEYARD
 ├── AUDIT ──▶ findings · chain verification · custody queries · integrity
 └── SYSTEM ──▶ agents alive · queue depth · model spend · cache · failures
```

---

## 5. Key views

### Agent detail

```
┌──────────────────────────────────────────────────────────────┐
│ AG-19 · "TA-CRYPTO"          Technical Analyst · CRYPTO desk │
│ Market Intelligence · TEAM-CRYPTO-MOMENTUM · SENIOR          │
├──────────────────────────────────────────────────────────────┤
│ STATE          ● IN MEETING — Research Review R-208          │
│ CHARTERS HELD  11 Technical Analyst · 13 Regime Analyst      │
│ SKILLS         stats.deflated_sharpe@2 · integrity.leak@1    │
│ PLAYBOOKS      research.test_cross_sectional_signal@3        │
│ TOOLS          engine.backtest.crypto · data.ohlcv · ...     │
│ CAN SEE        [view registry — click to inspect]            │
│ CAN WRITE      MarketObservation · Finding · Objection       │
├──────────────────────────────────────────────────────────────┤
│ LAST 30 DAYS   41 observations · 6 hypotheses · 12 critiques │
│ CALIBRATION    Brier 0.19 · 34 scored forecasts   [chart]    │
│ QUALITY        4 findings survived replication, 2 failed     │
│ AUDIT          1 finding against (MINOR, resolved)           │
│ COST           $2.14 · 96 model calls · 61% cached           │
├──────────────────────────────────────────────────────────────┤
│ CAREER  hired 08-14 ← fission of AG-04 · promoted SENIOR 08-29│
└──────────────────────────────────────────────────────────────┘
```

Note **CAN SEE** and **CAN WRITE**. Inspecting an agent's permissions is a
click, which is what makes the separation-of-duties design legible rather than
theoretical.

### Meeting view

The room, the participants at their seats, and the full transcript. Each turn
shows its speaker, its stance, the evidence it cited (clickable), and whether
the speaker changed position. The decision panel shows the outcome **and the
dissent**, with the dissenter's reasoning intact. Action items link to their
task rows. Header carries rounds used, tokens, cost, and whether the meeting
was productive.

### Experiment view

Hypothesis · registration hash and lock time · the exact spec · code version ·
data fingerprint · seed · every metric with its source artifact · the forecast
made before it ran · objections and their discriminating tests · replications ·
robustness grid · the derived verdict and the rule that derived it.

The question "why does the company believe this?" is answered by scrolling.

### Strategy view

State, thesis, version history, gates passed and failed with evidence, paper
record against backtest expectation, correlation with the rest of the book,
known weaknesses, open objections, and the full decision chain that promoted
it.

Never a single performance number presented as proof of quality.

### The Graveyard

A full room. Every refuted and inconclusive hypothesis, searchable by desk,
family, failure mode and date, with the reason it died and what was learned.
When a Brainstorm loads prior art, this is what it reads.

### Company timeline

```
09:01  INTEL/AG-19    posted briefing — unusual basis behaviour, OPTIONS
09:07  RESEARCH/AG-06 registered hypothesis H-1842
09:14  REGISTRY       locked REG-772 · hash 4a1e…
09:31  ENGINE         run 1183 completed · artifact 9f3c…
09:34  STRAT/AG-09    objection OBJ-31 SURVIVORSHIP + discriminating test
09:38  MEETING        Research Review R-208 convened · 5 participants
09:42  ENGINE         discriminating test complete — Sharpe 1.47 → 0.86
09:44  MEETING        AG-06 changed position · concedes
09:47  DECISION       H-1842 → REFUTED · dissent: none · 2 follow-ups
09:51  KNOWLEDGE      lesson recorded · 6 dependent findings annotated
```

This is what makes the organization feel alive, and it is a projection of the
event table — ordered, actored, subjected — so it costs nothing to produce.

---

## 6. Live vs. sealed

Two modes, and the page always says which.

| Mode | Source | Use |
|---|---|---|
| **Live** | Database + content store, SSE on ledger append | Day-to-day operation |
| **Sealed snapshot** | Committed artifacts only, single static file | Citing a result; reproducible from a clean clone; survives the database |

The sealed build is how a finding becomes referenceable. It renders from
artifacts alone, so it cannot drift from the record it describes.

---

## 7. Technology

| Concern | Choice |
|---|---|
| Server | FastAPI over read-only projections |
| Push | SSE on ledger append — traffic is server → client only |
| Rendering | Server-generated SVG facility + a light interactive shell for pan/zoom/drill-down |
| State | Projections rebuilt from events; the station holds no authoritative state |
| Static build | `aurelis station build --out site/station.html` — single file, vector only |

Deliberately **not** a heavyweight SPA by default. The facility is a generated
drawing; a full framework earns its place only if drill-down proves painful in
the light shell, and that would be recorded as an ADR when the pain appears.

---

## 8. What "operable without a terminal" means concretely

The station must let you:

- open a mission, set its objective, budget and desks
- see every agent, what it is doing, what it can see, what it costs
- read any meeting, including the arguments and the dissent
- trace any claim to the artifact that produced it
- browse the graveyard and understand what failed and why
- approve or reject an org change the company proposed for itself
- see risk limits, and every veto
- watch paper trading and the live-vs-backtest gap
- acknowledge alerts and read incident reviews
- verify the ledger chain and the custody query budget

If any of those requires a terminal, the station is not finished.

And the questions it must answer at a glance, from `CLAUDE.md` §35: *What is
happening? Why? Who is doing it? What has the company learned? What is it going
to do next? What strategies exist and why do we believe in them? What risks
exist? What failed? What needs attention?*
