# Aurelis

**An autonomous quantitative research corporation.**

Ten departments. Seven market desks. Seventy-six role charters. Agents that
observe, hypothesize, experiment, argue in meetings, decide, build strategies,
manage risk, trade on paper, remember everything — and expand the organization
themselves as the evidence justifies it.

[![CI](https://github.com/martex-dev/aurelis/actions/workflows/ci.yml/badge.svg)](https://github.com/martex-dev/aurelis/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Status: **M9 complete — paper trading, and the measurement reality votes on.**
An order cannot exist without the approval chain behind it. The backtest-live
gap is measured against the artifact that justified deployment, and every
deployment forecasts its own gap. · 2026-09-06

> Research software. No live trading adapter exists. Nothing here is proven
> profitable. Read [DISCLAIMER.md](DISCLAIMER.md).

---

## Try it

```bash
pip install -e ".[dev]"
aurelis db init            # schema, invariants, the org chart
aurelis agent hire         # staff the launch roster
aurelis research review    # the demonstration
aurelis memory import      # inherited trials, gap and all
aurelis station serve      # Mission Control on http://127.0.0.1:8787/
```

### The demonstration

```
HYP-0001  CONFIRMED -> REFUTED

 claimed           max_drawdown < 0.20, measured 0.12364208
 universe          3 names (still trading)
 objection         OBJ-0001 SURVIVORSHIP, critical
 test              the same rule, universe restored to point-in-time
 re-run universe   6 names
 restored          LUNC/USDT, FTT/USDT, HOTAIR/USDT
 max_drawdown      0.12364208 -> 0.64507263
 verdict           UPHELD
 chain             chain verified: 68 events, seq 1..68
```

A researcher registers a drawdown claim over the instruments still trading,
runs it, and it is **confirmed**. A Critic names `SURVIVORSHIP` — it does not
write the test; the taxonomy generates it from the specification under review.
The Chair dispatches it. The point-in-time re-run restores three delisted names
and drawdown goes from 12% to 65%. The objection is upheld and the claim is
**refuted by a measurement**.

Nobody intervenes at any point.

*martex-quant found this same defect on real crypto history, where it took a
Sharpe of 1.47 to 0.86. Those figures belong to that corpus; the ones above are
what this engine measured on fixture instruments where the bias is present by
construction.*

### What the company already knows

```
aurelis memory import

imported 21 ledger entries from martex-quant (29 hypothesis documents)
  claimed by the source      125
  documented by its entries  120
  unallocated                5
  carried because            Documented per-hypothesis deltas do not sum to
                             the ledger's stated total. The gap is reported,
                             not absorbed.
  reconciles                 yes
```

The import **reproduces the source's own arithmetic instead of tidying it**.
125 claimed, 120 accounted for by its committed documents, and a five-trial gap
that the source itself says would be fabrication to distribute. Deflated
Sharpes arrive as published — `0.99 against 65 trials`, never re-deflated
against Aurelis's own count, because that would restate a figure somebody else
computed.

That is the snapshot bundled in the installed wheel, so the import is
reproducible from the lockfile alone. `--bundle <repo>` reads a live
repository instead — 174 claimed, 169 documented, the same gap of five. The
reconciliation row stores the SHA-256 of whichever ledger was read, so a corpus
that changed under a re-import is detectable rather than silently merged.

Ask whether an idea is new, and the answer comes from the record:

```
aurelis memory prior-art "Do funding rate extremes predict forward returns?"   --family info.derivatives.funding

MQ-H08 (martex-quant, killed) - close match on extremes, funding
```

That answer is now in every Brainstorm's evidence pack before anyone speaks.

Confidence is **derived, never stored**, which is what makes it degrade on its
own:

```
aurelis memory confidence FND-0001

FND-0001  none
  verdict             confirmed
  independent support 1
  capped by           OBJ-0001 was upheld by measurement: survivorship
```

The finding still says `confirmed`. Nobody edited it, and nobody had to
remember to. An objection was upheld against the claim, so the company is no
longer entitled to believe it — and the reason is on the record rather than in
somebody's head. Support is counted the same way: three results that correlate
above 0.7 collapse to one, and the discount **says what it discounted** instead
of quietly returning a smaller number.

There is no confidence column to go stale, which is the whole point
([ADR-0008](docs/adr/0008-confidence-is-derived-never-stored.md)).

### Building a strategy, rather than picking one

The corpus Aurelis inherited holds 125 crypto trials. The obvious thing to
build on top of it is a pipeline that promotes the best one. That system is a
**selection engine**: it produces whatever the corpus already contains and
stops the day the corpus runs out.

So there is no `promote_hypothesis`, no `from_finding`, and no
`hypothesis_ref` column on a strategy version — a test asserts the absence of
each. A strategy is *composed* from pieces agents wrote:

```
aurelis strategy components

ref        kind    name                     origin                cites
CMP-0001   signal  funding skew reversal    derived_from_failure  HYP-0001
CMP-0002   sizing  inverse vol sizing       invented              MTG-0001
CMP-0003   signal  funding skew, basis-neu… refined               CMP-0001
```

Every component states why it should work and cites where it came from, and
the citation *shape* is checked — an `INVENTED` component may not cite a corpus
trial, because then it was not invented. A refuted hypothesis is material, not
a candidate: `DERIVED_FROM_FAILURE` is the only bridge from research, which is
what a graveyard is actually for.

That makes novelty measurable rather than claimed:

```
SV-0002: 1 of 2 component(s) authored here, 0 inherited (1 invented, 1 refined)
```

**And a market is not a market.** Those 125 trials were run on crypto alone,
while the company covers seven desks. A funding-rate signal is not a market
regularity — it is a perpetual-swap regularity — so a version is native to one
desk and unproven on the others until measured there:

```
crypto       native — composed and measured on this desk
equities     inapplicable — CMP-0001 assumes perpetual_funding
futures      inapplicable — CMP-0001 assumes perpetual_funding
```

`INAPPLICABLE` is not a failed backtest. It says the test could not mean
anything, which is worth more than the number it prevents. The reasoning is in
[ADR-0010](docs/adr/0010-strategies-are-composed-not-promoted.md).

Deployment is gated on criteria registered **before** they are evaluated, and
gate C is the one that bites: six gates pass, the correlation with the deployed
book does not, and the version stays at `UNDER_REVIEW`. Once a version *is*
promoted the database freezes its spec — a material change becomes a new
version, so no result row can quietly end up describing something else.

Risk is an authority rather than a reviewer. `approve()` takes no exposure
argument at all; it reads the permitted size off the assessment, and a trigger
refuses an approval that borrows another proposal's assessment or exceeds what
Risk allowed. All three numbers are always persisted:

```
desired 12000 -> allowed 5000 -> final 5000     SHRINK
```

so "Risk allowed it" and "Risk was never asked" are different rows rather than
the same silence.

### Paper trading, and the one measurement reality votes on

An order cannot exist without the chain behind it. `aurelis trading chain`
walks one backwards:

```
ORD-0001  filled
  TPR-0001  proposed by AG-0012: paper cycle intent for SV-0001
  RSK-0001  SHRINK by AG-0011
      desired 12000 exceeds the tightest live limit 5000 (desk: new desk,
      unproven in paper)
  TAP-0001  approved by AG-0013
  ORD-0001  buy 50 BTC/USDT on the paper broker
      filled 50 at 100.025 (fee 5.00)

The three numbers
  desired  12000    allowed  5000    final  5000
```

Four rows, four different write scopes, four different roles. The agent that
wants the exposure is not the one that permits it and not the one that sends
the order — enforced by database triggers, not by everyone remembering.

**There is no live broker.** Not disabled — absent: no adapter, no enum member,
no registry entry, and `resolve("live")` refuses with an explanation rather
than a `KeyError`. A test parses every module's imports to prove nothing can
reach martex-quant's MT5 adapter.

The gap is what M9 exists for:

```
SV-0001 max_drawdown: backtest 0.12364208, paper 0.17364208 (+0.05) — fell short
deployment forecast 0.7 that it would hold → outcome False, Brier 0.49
```

The expectation is copied from the run that justified deployment, **with its
artifact digest** — not recomputed, because re-deriving it would compare paper
against today's estimate rather than against the claim actually made. And the
mean gap is tracked as a company competence: how wrong our backtests tend to be
is a fact about us, not about any one strategy.

### The window

```bash
aurelis station serve
```

A facility drawn from the registries and lit by the record. Ten department
rooms, a bay per desk, the Graveyard as a full room — and the Registry and the
Vault with **no corridor**, because you cannot walk into a process boundary.
Staff figures are the headcount: a room with three people has three, and a room
with none is drawn unlit at full size rather than left out.

The rule that makes it trustworthy is a type:

```python
Figure(42)                                  # TypeError — no source
Figure(42, Source.table("agents", "..."))   # fine, and hovering shows the query
```

`Figure` has no constructor that omits its source, so a number cannot reach a
page without naming the row, artifact or registry entry it came from. "Nothing
on this page was typed" is checkable by reading the type rather than by
auditing every call site. Where nothing was measured, the page says `NO DATA`
and why — never `0`, because a zero is a measurement and the two justify
different conclusions.

Open `/hypothesis/HYP-0001` after the demonstration and the whole story is one
page: the claim, the preregistration hash and its lock time, the criteria
committed before the run, the code version and data fingerprint, every metric
with `computed_by = ENGINE`, the survivorship objection, and the measurement
that killed it. *Why does the company believe this?* is answered by scrolling.

`aurelis station build` writes the same record to a single file that fetches
nothing — no stylesheet, script, font or image — stamped with the ledger head
and the chain verification, so a finding can be cited years after the database
has moved on.

### The rest of the company

`aurelis mission run` opens a mission with a **Kickoff meeting**, plans a
project into three dependency-sequenced tasks, runs them, and closes with a
**Retrospective** that scores the kickoff's forecasts against what happened.
**INTEL** briefs the desk, **QUANT** checks that briefing against a window it
measured itself, **LEAD-R** decides. There is no orchestrator — a task whose
dependency has not succeeded is simply invisible to the queue.

`aurelis research run` takes a single hypothesis from claim to verdict:
propose, screen for prior art, **lock a preregistration**, design, run, and
derive the verdict from criteria fixed before anything executed. On 240 bars it
returns `UNDERPOWERED`, because 240 bars genuinely cannot detect a Sharpe of
0.05 — and saying so is the point.

Look around:

| | |
|---|---|
| `aurelis org show` · `org desks` · `org charters` | the company as designed |
| `aurelis agent list` · `agent show INTEL` | what one agent holds, sees, writes, may invoke |
| `aurelis mission show MSN-0001` | every task, its status, what it waits on |
| `aurelis meeting show MTG-0001` | the transcript, who changed their mind, who dissented |
| `aurelis meeting calibration` | how good the company's forecasts have been |
| `aurelis research show HYP-0001` | every metric, its interval, and who computed it |
| `aurelis research graveyard` | everything killed, and why |
| `aurelis research defects` | every market defect and how it is settled |
| `aurelis tick` · `aurelis doctor` | advance the working day; check the workspace |

---

## Read in this order

| Doc | Covers |
|---|---|
| [`docs/00-audit.md`](docs/00-audit.md) | What already exists on this machine and what it is worth |
| [`docs/01-architecture.md`](docs/01-architecture.md) | The system: layers, repository, agent runtime, communication, desks, engines, self-improvement, platform, cost, safety, testing |
| [`docs/02-organization.md`](docs/02-organization.md) | The company: 10 departments, 7 desks, **all 76 role charters**, launch roster, role fission, permissions, skills, careers |
| [`docs/03-meetings.md`](docs/03-meetings.md) | How agents work together: 11 meeting types, the 7-phase protocol, brainstorming, debate, cost control |
| [`docs/04-domain-model.md`](docs/04-domain-model.md) | Every entity, its lifecycle, and who may write it |
| [`docs/05-lifecycles.md`](docs/05-lifecycles.md) | Research → strategy → portfolio → risk → trading |
| [`docs/06-mission-control.md`](docs/06-mission-control.md) | The station: the facility, drill-down, every view |
| [`docs/07-roadmap.md`](docs/07-roadmap.md) | M0–M13, each with an acceptance test |
| [`docs/adr/`](docs/adr/) | The ten decisions that are hard to reverse |

---

## What Aurelis is

A corporation of AI agents that researches markets and builds systematic
strategies. The software's job is to make the company *function*: departments,
desks, teams, colleagues, meetings, tools, memory, budgets, careers, and a
building to work in.

```
EXECUTIVE ─── missions, priorities, org development, the Chair
    │
    ├── MARKET INTELLIGENCE ────┐
    ├── QUANTITATIVE RESEARCH ──┤
    ├── STRATEGY LABORATORY ────┤    × 7 DESKS
    ├── PORTFOLIO & RISK ───────┤    crypto · equities · options · futures
    ├── TRADING OPERATIONS ─────┤    commodities · FX · memecoins
    ├── AUDIT & GOVERNANCE ─────┤
    ├── KNOWLEDGE & MEMORY ─────┘
    ├── INFRASTRUCTURE
    └── INSTITUTIONAL GOVERNANCE ─── serves the other nine, replaces none
```

Agents work individually. Teams work together. **Meetings decide.**

---

## Decisions taken

**1. New repository, new architecture.** Aurelis is its own system.

- **martex-quant** is a *tool in the toolbox* — one research engine (crypto),
  a validated data lake, and a statistics library, reached only through
  `engines/martex/`. It helps researchers with part of their work. It generates
  no hypotheses, decides nothing, and no agent ever sees it except as tool
  calls.
- **nullius** contributes platform *patterns* (hash-chained ledger,
  preregistration triggers, evidence typing, budget accounting) and staffs
  **one service department** — Institutional Governance — whose eleven officers
  serve the other nine. They have no authority over research direction and
  replace nobody.
- Everything else is Aurelis's own. ([ADR-0001](docs/adr/0001-aurelis-is-its-own-system.md))

**2. Wide scope from the start.** Seven market desks: crypto, equities,
options, futures, commodities, FX, memecoins. A desk is an orthogonal
dimension crossing every department; an agent is `(role, desk)`. Opening a desk
is registering a config and staffing it — no architectural change.
([ADR-0004](docs/adr/0004-market-desks-are-the-second-dimension.md))

**3. Subscription-first, minimum cost.** Everything runs on the Claude Pro
subscription through a provider abstraction until a budget is set; switching to
a metered API is a config change. Deterministic work costs nothing, models are
tiered by seniority, meetings are budgeted, idle is free, and the entire system
is testable at zero cost through a mock provider.
([ADR-0007](docs/adr/0007-subscription-first-model-access.md))

**4. Meetings are first-class — and they work.** Real multi-round discussion
with a full kept transcript. Kickoff at the start of every mission and project,
Retrospective at the end, both enforced by the state machine. Plus Brainstorm,
Research Review, Debate, Strategy Committee, Risk Committee, Incident Review,
Standup, Board and All-Hands as needed.

The mechanism that makes debate end in evidence rather than in exhaustion:
**every objection must carry a discriminating test** — an executable spec that
would settle it — and the Chair runs it, in the meeting, with everyone
watching. ([ADR-0002](docs/adr/0002-meetings-are-first-class.md))

---

## All 76 charters, covered from day one

The full org chart from `CLAUDE.md` §4 exists from the start — as **charters**.
Seventeen launch agents hold them as generalists, and each agent's record says
exactly which future specialists it is standing in for.

| Launch | Holds | Becomes |
|---|---|---|
| AG-04 INTEL | all 9 Market Intelligence charters | Fundamental, News, Sentiment, Technical, Macro, Regime, AltData, Source Reliability, Head |
| AG-06 QUANT | 7 research charters | Statistical, Backtest, Simulation, ML, Factor, Data Scientist, Quant |
| AG-13 TRADE | all 7 Trading charters | Setup, Planner, Approval, Execution, Monitor, Post-Trade, Head |
| AG-14 AUDIT | all 6 Audit charters | Research, Data, Backtest, Execution, Behaviour auditors, Chief |
| … | … | … |

Then the company splits its own roles as evidence justifies:

```
17 agents ──▶ ~28 ──▶ ~45 ──▶ ~80 ──▶ 100+
1 desk        2        4        7        7
```

**Role fission** is the mechanism. Every agent carries measured load and
quality; when a threshold trips, the Org Development Lead proposes a split with
evidence and a predicted effect, a Board meeting decides, the new specialist is
hired and onboarded, and the effect is measured afterwards — recorded even when
the split made nothing better.

That is `CLAUDE.md` §16's "4 researchers, 2 fundamental analysts" reached by
measurement. **Nothing in the runtime changes across those stages** — agents are
rows, roles are charters, desks are configs. Growth is data.
([ADR-0003](docs/adr/0003-role-fission-is-the-growth-mechanism.md))

---

## How the company knows it is getting better

Self-improvement is core and stays core. Three measurements, none circular:

1. **Forecast calibration.** Every agent records a probability before every
   experiment and every meeting outcome, and it is scored afterwards. One cheap
   call each, per-agent quality signal, no LLM grading another LLM's prose.
2. **Training scenarios.** A synthetic engine generates research problems where
   the answer is known — planted effects of stated size, planted leaks, planted
   survivorship bias, and a large fraction with nothing in them. New agents are
   scored before they start work; org changes are measured by running the same
   suite with and without; playbook revisions that lower the catch rate fail
   CI. Runs offline and cheaply.
   ([ADR-0005](docs/adr/0005-training-scenarios-measure-agents-and-org-changes.md))
3. **Forward paper performance.** The backtest-vs-live gap, per strategy and
   per desk — the only measurement where reality gets a vote.

---

## The two rules that make it a research company

**Agents interpret. Software computes.** No metric, verdict or confidence is
ever produced by a model. A turn or finding containing a numeral that is not in
the evidence pack or a tool result is rejected by a validator.

**Everything traces to evidence.** Findings carry evidence refs; evidence
carries artifact hashes; artifacts carry the spec, seed, data fingerprint and
code version that produced them. In Mission Control, every number on screen
opens its source.

Supporting them: preregistration locked and hashed before any run (database
trigger, not a prompt), an append-only hash-chained ledger, risk that cannot be
bypassed (foreign key, not instruction), sealed out-of-sample data behind a
process boundary with a counted query budget, and no live trading adapter in
the repository at all ([ADR-0006](docs/adr/0006-live-execution-is-absent-not-disabled.md)).

---

## Mission Control

The primary interface. A cutaway industrial facility — pixel-art-inspired, dark
sci-fi, dense but readable — where every room is a department, every bay on the
floor is a desk, and every figure on screen names the artifact it was read from.

Click a department to open it. Click an agent to see what it is doing, what it
can see, what it can write and what it costs. Click a meeting to read the
argument, the evidence cited, who changed their mind, and who dissented. Click
a strategy to see why the company believes in it. The Graveyard is a full room,
not a hidden tab.

Two rooms have no corridor into them — the Registry and the Vault — because you
genuinely cannot walk into a process boundary.

---

## The first real demonstration

By **M5**: given a strategy specification whose universe was chosen with
hindsight, the Strategy Critic raises a `SURVIVORSHIP` objection, attaches a
discriminating test, the Chair dispatches it inside a Research Review meeting,
the point-in-time run comes back with the Sharpe collapsed, the author concedes
on the record, and the hypothesis is refuted — **with no human in the loop.**

That is a real discovery from the existing research corpus, reproduced
automatically by the company, five milestones in.

---

## Milestones

| | | |
|---|---|---|
| **M0** ✅ | Foundations | ledger, budgets, artifacts, queue, provider abstraction |
| **M1** ✅ | Agent runtime | 76 charters, 17 agents, permissions, views, tools, the loop |
| **M2** ✅ | Missions | missions → projects → tasks, dependencies, the working day |
| **M3** ✅ | **Meetings** | seven-phase protocol, forecasts, objections with tests, dissent |
| **M4** ✅ | Research lifecycle | engines, preregistration, experiments, verdicts |
| **M5** ✅ | Critique & audit | market defects, point-in-time, the review that kills |
| **M6** ✅ | Memory & knowledge | graph, lessons, corpus import, vault export |
| **M7** ✅ | **Mission Control** | the live facility, every figure sourced |
| **M8** ✅ | Strategy, portfolio, risk | authored components, gates, veto |
| **M9** ✅ | Paper trading | approval chain, the backtest-live gap |
| **M10** | Training scenarios | onboarding and playbook regression |
| **M11** | **Org development** | the company grows itself |
| **M12** | Multi-desk | equities → options → futures → commodities → FX → memecoins |
| **M13** | Scale | 100+ agents, seven desks, hardening |

Full acceptance criteria in [`docs/07-roadmap.md`](docs/07-roadmap.md).

---

## What success looks like

Multiple specialized agents genuinely collaborating. Research that is
reproducible. Failed research preserved and used. Strategies versioned and
evidence-backed. Risk that is independent. A company that learns from its
results and improves its own structure on measured evidence. And a human who
can operate and understand the whole thing through Mission Control without
opening a terminal.

Profitability is what the company is built to *pursue* — through evidence,
across seven markets, with an organization that keeps getting better at
looking. It is not assumed, and the system is built so that it can say when it
has not found one.
