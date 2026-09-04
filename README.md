# Aurelis

**An autonomous quantitative research corporation.**

Ten departments. Seven market desks. Seventy-six role charters. Agents that
observe, hypothesize, experiment, argue in meetings, decide, build strategies,
manage risk, trade on paper, remember everything — and expand the organization
themselves as the evidence justifies it.

[![CI](https://github.com/martex-dev/aurelis/actions/workflows/ci.yml/badge.svg)](https://github.com/martex-dev/aurelis/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Status: **M3 complete — the company meets, argues and decides.** 76 charters,
17 agents, meetings with forecasts, objections that carry tests, and dissent on
the record. · 2026-09-04

> Research software. No live trading adapter exists. Nothing here is proven
> profitable. Read [DISCLAIMER.md](DISCLAIMER.md).

---

## Try it

```bash
pip install -e ".[dev]"
aurelis db init          # schema, invariants, the org chart
aurelis agent hire       # staff the launch roster
aurelis mission run      # open a mission and work it to completion
aurelis doctor
```

`mission run` opens a mission with a **Kickoff meeting**, plans a project into
three dependent tasks, runs them, and closes with a **Retrospective** that
scores the kickoff's forecasts against what actually happened.

Between the meetings: **INTEL** briefs the crypto desk from measured bars.
**QUANT** reads that briefing, checks it against an independent window it
measured itself, and raises a research question. **LEAD-R** decides whether the
question earns a project. Each waits for the one before because the queue will
not hand out a task whose dependency has not succeeded — there is no
orchestrator.

```
 mission         MSN-0001
 kickoff         MTG-0001 — 5 turns, 0 exchange round(s)
 turns           3
 progress        3/3 succeeded
 retrospective   MTG-0006 — 5 turns
 calibration     AG-0004: Brier 0.2500 over 1 forecast — no better than 50/50
 chain           chain verified: 141 events, seq 1..141
```

Look around: `aurelis org show` · `aurelis org desks` · `aurelis agent list` ·
`aurelis agent show INTEL` (what one agent holds, sees, writes and may invoke)
· `aurelis mission show MSN-0001` (every task, its status, what it waits on) ·
`aurelis tick` (advance the working day one turn).

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
| [`docs/adr/`](docs/adr/) | The seven decisions that are hard to reverse |

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
| **M4** | Research lifecycle | engines, preregistration, experiments, findings |
| **M5** | Critique & audit | objections with tests, the H71 reproduction |
| **M6** | Memory & knowledge | graph, lessons, corpus import, vault export |
| **M7** | **Mission Control** | the live facility |
| **M8** | Strategy, portfolio, risk | versions, gates, veto |
| **M9** | Paper trading | approval chain, the backtest-live gap |
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
