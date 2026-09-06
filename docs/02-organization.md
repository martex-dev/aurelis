# 02 — The Organization

Date: 2026-09-04
Status: proposal, v2.

The complete company: ten departments, seven market desks, sixty-seven role
charters, and the mechanism by which the company grows itself from a launch
roster of sixteen agents to forty, then to hundreds.

---

## 1. Principles

1. **A role is a charter, not an agent.** The charter is the full remit. An
   agent *holds* some coverage of a charter. Several agents may hold the same
   charter on different desks.
2. **Every charter area is owned by someone at all times.** A launch agent
   holding six charters is explicitly standing in for six future specialists.
   Coverage is never dropped — only reassigned.
3. **Growth is earned and recorded.** Splitting a role, hiring an agent,
   opening a desk: each is an `OrgChange` with a trigger, evidence, and a
   meeting decision behind it.
4. **Specialisation is the point.** A researcher may not trade. An analyst may
   not decide portfolio exposure. Risk may veto anyone. An auditor may
   challenge anything. Separation of duties is enforced by write scopes, not
   by instruction.
5. **Seniority is real.** Junior agents produce; senior agents review; leads
   assign and represent the team in meetings; directors set direction. Model
   tier follows seniority, which is also how cost follows importance.

---

## 2. The ten departments

| # | Department | Owns | Head |
|---|---|---|---|
| 1 | **Executive / Mission Control** | Company direction, missions, priorities, org development, the Chair | Company Manager |
| 2 | **Market Intelligence** | Observation, evidence gathering, briefings, market state | Head of Market Intelligence |
| 3 | **Quantitative Research** | Hypotheses, experiments, statistics, modelling, research engineering | Research Director |
| 4 | **Strategy Laboratory** | Strategy discovery, synthesis, debate, adversarial testing, validation | Head of Strategy |
| 5 | **Portfolio & Risk** | Construction, allocation, exposure, correlation, risk authority | Chief Risk Officer |
| 6 | **Trading Operations** | Setup analysis, trade planning, approval, execution, monitoring | Head of Trading |
| 7 | **Audit & Governance** | Independent challenge of research, data, backtests, execution, agents | Chief Auditor |
| 8 | **Knowledge & Memory** | Institutional memory, archive, registries, ledger, knowledge graph | Chief Knowledge Officer |
| 9 | **Infrastructure** | Data systems, compute, scheduling, runtime, observability, integrations | Head of Infrastructure |
| 10 | **Institutional Governance** | Preregistration, custody, evidence typing, forecast scoring, budget ledger — **in service to the other nine** | Governance Director |

Department 10 is where nullius's eleven officers live. They are a **service
department**, like legal or compliance in a real firm: every department uses
them, none reports to them, and they replace nobody.

---

## 3. The seven market desks

Desks cross departments. An agent is `(role, desk)`.

| Desk | Instruments | Engines | Key data |
|---|---|---|---|
| **CRYPTO** | spot, perpetuals, funding, basis | martex-quant | ccxt lake, funding, on-chain |
| **EQUITIES** | single names, ETFs, indices | equities engine | prices, fundamentals, filings, factor models |
| **OPTIONS** | listed options, vol surfaces | options engine | chains, IV, greeks, term structure |
| **FUTURES** | index, rates, term structure | futures engine | continuous contracts, roll calendars |
| **COMMODITIES** | energy, metals, agriculture | futures engine | curves, inventories, seasonality |
| **FX** | majors, crosses, carry | fx engine | bars, rate differentials, central bank calendar |
| **MEMECOINS** | micro-cap tokens, launches | martex-quant `meme/` | DexScreener, GeckoTerminal, wallet cohorts |

Desks open in stages. CRYPTO first (the data lake and engine already exist),
then EQUITIES, then OPTIONS, then the rest. Opening a desk is registering a
`DeskConfig` and staffing it — no architectural change.

**Desk × role is the multiplier that takes the company to hundreds of agents.**
Seven desks × a forty-role roster is a 280-agent ceiling, reached only where
evidence justifies each hire.

---

## 4. The full role roster — 67 charters

Every role listed in `CLAUDE.md` §4, plus the roles the architecture requires.
`Tier` is the model tier. `Launch` says which launch agent stands in for it
(see §5).

### 4.1 Executive / Mission Control

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 1 | **Company Manager (CEO)** | Company direction, mission portfolio, final escalation, chairs the Board | High | AG-01 |
| 2 | **Research Director (CIO)** | Research agenda, what gets studied, allocation of research effort | High | AG-02 |
| 3 | **Operations Director** | Throughput, blockers, scheduling, department health | Mid | AG-03 |
| 4 | **Mission Orchestrator** | Decomposes missions into projects and tasks, tracks progress | Mid | AG-03 |
| 5 | **Chief of Staff / Chair** | Runs meetings: agenda, rounds, budget, minutes, action items | Mid | AG-03 |
| 6 | **Org Development Lead** | Watches org metrics, proposes fission/fusion/hiring, runs org experiments | Mid | AG-02 |

### 4.2 Market Intelligence

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 7 | **Head of Market Intelligence** | Briefing quality, source coverage, desk intelligence priorities | Mid | AG-04 |
| 8 | **Fundamental Analyst** | Financial statements, valuation, earnings, sector economics | Mid | AG-04 |
| 9 | **News Analyst** | Event detection, materiality, timeline reconstruction | Low | AG-04 |
| 10 | **Sentiment / Social Analyst** | Positioning, crowding, social signal with base rates attached | Low | AG-04 |
| 11 | **Technical Analyst** | Price structure, trend, volatility, microstructure observation | Mid | AG-04 |
| 12 | **Macro Analyst** | Rates, growth, inflation, policy, cross-asset linkage | Mid | AG-04 |
| 13 | **Regime Analyst** | Regime identification, transitions, conditional behaviour | Mid | AG-04 |
| 14 | **Alternative Data Analyst** | On-chain, flows, positioning, novel sources and their reliability | Mid | AG-04 |
| 15 | **Source Reliability Officer** | Tracks every source's freshness, revisions, historical accuracy | Low | AG-04 |

### 4.3 Quantitative Research

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 16 | **Lead Researcher** | Owns a research programme, assigns work, defends findings | High | AG-05 |
| 17 | **Quant Researcher** | Designs and runs experiments, forms hypotheses | Mid | AG-06 |
| 18 | **Statistical Researcher** | Test selection, power, multiple testing, confidence intervals | Mid | AG-06 |
| 19 | **Backtest Researcher** | Backtest design, cost realism, walk-forward protocol | Mid | AG-06 |
| 20 | **Simulation / Monte Carlo Researcher** | Path simulation, bootstrap, prop-rule and ruin analysis | Mid | AG-06 |
| 21 | **ML Researcher** | Learned models, feature design, purged CV, calibration | Mid | AG-06 |
| 22 | **Factor Researcher** | Factor construction, exposure, spanning tests | Mid | AG-06 |
| 23 | **Research Engineer** | Builds experiment specs, engine adapters, data pipelines, tooling | Mid | AG-07 |
| 24 | **Data Scientist** | Exploratory analysis, visualisation, anomaly surfacing | Mid | AG-06 |

### 4.4 Strategy Laboratory

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 25 | **Head of Strategy** | Strategy portfolio, promotion agenda, chairs Strategy Committee | High | AG-08 |
| 26 | **Strategy Architect** | Turns findings into strategy designs: entries, exits, sizing | High | AG-08 |
| 27 | **Strategy Discovery Agent** | Systematic search over the hypothesis space for candidates | Mid | AG-08 |
| 28 | **Strategy Synthesizer** | Combines signals and strategies into coherent specifications | Mid | AG-08 |
| 29 | **Strategy Critic** | Attacks the design: assumptions, fragility, hidden costs | Mid | AG-09 |
| 30 | **Adversarial Researcher** | Actively tries to break results; hunts for the reason it is wrong | Mid | AG-09 |
| 31 | **Replication Researcher** | Independent re-test with a deliberate declared variation | Mid | AG-10 |
| 32 | **Robustness Researcher** | Parameter, period, universe, cost and regime stress grids | Mid | AG-10 |
| 33 | **Validation Researcher** | Runs promotion gates; owns the out-of-sample request | Mid | AG-10 |

### 4.5 Portfolio & Risk

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 34 | **Chief Risk Officer** | Risk authority, limits, veto, kill switches, chairs Risk Committee | High | AG-11 |
| 35 | **Risk Manager** | Per-strategy and per-desk risk assessment on every proposal | Mid | AG-11 |
| 36 | **Portfolio Manager** | Portfolio construction from approved strategy signals | Mid | AG-12 |
| 37 | **Exposure Analyst** | Gross, net, concentration, sector, desk and factor exposure | Mid | AG-11 |
| 38 | **Correlation Analyst** | Inter-strategy correlation, drawdown interaction, diversification | Mid | AG-11 |
| 39 | **Capital Allocation Analyst** | Allocation across strategies and desks; capacity analysis | Mid | AG-12 |
| 40 | **Stress Testing Analyst** | Scenario and historical stress, tail behaviour, liquidity shock | Mid | AG-11 |

### 4.6 Trading Operations

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 41 | **Head of Trading** | Operational integrity of everything that reaches a broker | Mid | AG-13 |
| 42 | **Market Setup Analyst** | Whether current conditions suit an approved strategy | Mid | AG-13 |
| 43 | **Trade Planner** | Turns target exposure into an executable plan | Mid | AG-13 |
| 44 | **Trade Approval Agent** | Final gate: checks approval chain, limits, and halts | Low | AG-13 |
| 45 | **Execution Agent** | Submits orders through the broker adapter; nothing else | Low | AG-13 |
| 46 | **Position Monitor** | Live positions, drawdown, divergence from expectation | Low | AG-13 |
| 47 | **Post-Trade Analyst** | Slippage, cost attribution, backtest-vs-live gap | Mid | AG-13 |

### 4.7 Audit & Governance

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 48 | **Chief Auditor** | Independent challenge authority across the whole company | High | AG-14 |
| 49 | **Research Auditor** | Preregistration compliance, HARKing, cherry-picking, spec drift | Mid | AG-14 |
| 50 | **Data Auditor** | Timestamps, revisions, survivorship, point-in-time correctness | Mid | AG-14 |
| 51 | **Backtest Auditor** | Look-ahead, cost realism, liquidity assumptions, leakage | Mid | AG-14 |
| 52 | **Execution Auditor** | Approval chains, limit breaches, unapproved orders | Low | AG-14 |
| 53 | **Agent Behavior Auditor** | Role-boundary violations, fabricated figures, unsupported claims | Mid | AG-14 |

### 4.8 Knowledge & Memory

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 54 | **Chief Knowledge Officer** | What the company knows, and how confident it is entitled to be | Mid | AG-15 |
| 55 | **Institutional Memory Keeper** | Lessons learned, standing rules, what not to repeat | Mid | AG-15 |
| 56 | **Research Archivist** | Every experiment, result and document, retrievable | Low | AG-15 |
| 57 | **Strategy Registrar** | Strategy registry, versions, states, promotion history | Low | AG-15 |
| 58 | **Hypothesis Ledger Keeper** | Every hypothesis and trial ever registered, including the dead | Low | AG-15 |
| 59 | **Knowledge Graph Curator** | Nodes, edges, dependency and contradiction structure | Mid | AG-15 |

### 4.9 Infrastructure

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 60 | **Head of Infrastructure** | Platform health, capacity, reliability | Mid | AG-16 |
| 61 | **Data Systems Engineer** | Ingestion, validation, storage, freshness, backfills | Mid | AG-16 |
| 62 | **Compute Manager** | Job scheduling, resource limits, queue health | Low | AG-16 |
| 63 | **Agent Runtime Manager** | Agent lifecycle, stuck workers, restarts, model routing | Low | AG-16 |
| 64 | **Observability Engineer** | Metrics, alerting, dashboards feeding the station | Low | AG-16 |
| 65 | **Integrations Engineer** | External APIs, brokers, feeds, credentials handling | Mid | AG-16 |

### 4.10 Institutional Governance (the nullius officers)

| # | Role | Charter | Tier | Launch |
|---|---|---|---|---|
| 66 | **Governance Director** | Owns the integrity machinery; reports findings to the Board | Mid | AG-17 |
| 67 | **Registrar** | Locks and hashes preregistrations before any run | None | AG-17 |
| 68 | **Custodian** | Holds sealed out-of-sample data; releases counted queries | None | AG-17 |
| 69 | **Evidence Officer** | Enforces evidence typing; rejects speculation promoted to fact | None | AG-17 |
| 70 | **Forecast Scorer** | Collects pre-run forecasts, scores them, publishes calibration | None | AG-17 |
| 71 | **Ledger Officer** | Verifies the hash chain, reconciles totals, reports tampering | None | AG-17 |
| 72 | **Budget Officer** | Hierarchical budgets, dispatch refusal, spend reporting | None | AG-17 |
| 73 | **Provenance Officer** | Every figure traces to an artifact; flags orphaned numbers | None | AG-17 |
| 74 | **Skeptic-in-Residence** | Standing adversarial review, independent of Strategy Lab | Mid | AG-17 |
| 75 | **Replication Officer** | Schedules and adjudicates independent replications | Low | AG-17 |
| 76 | **Peer Reviewer** | Structured review before any claim becomes institutional | Mid | AG-17 |

**Seventy-six charters.** Most of Institutional Governance is deterministic
software wearing a badge — which is deliberate, because "who computed this?"
must be a checkable field, and because these officers cost nothing to run.

---

## 5. The launch roster — 17 agents

Every charter above is covered from day one. Launch agents are **generalists
standing in for future specialists**, and each one's record says exactly which
charters it currently holds.

| Agent | Name | Department | Holds charters | Tier |
|---|---|---|---|---|
| **AG-01** | CEO | Executive | 1 | High |
| **AG-02** | CIO | Executive | 2, 6 | High |
| **AG-03** | OPS | Executive | 3, 4, 5 | Mid |
| **AG-04** | INTEL | Market Intelligence | 7–15 (all nine) | Mid |
| **AG-05** | LEAD-R | Quant Research | 16 | High |
| **AG-06** | QUANT | Quant Research | 17–22, 24 | Mid |
| **AG-07** | ENG-R | Quant Research | 23 | Mid |
| **AG-08** | STRAT | Strategy Lab | 25–28 | High |
| **AG-09** | CRITIC | Strategy Lab | 29, 30 | Mid |
| **AG-10** | VALID | Strategy Lab | 31–33 | Mid |
| **AG-11** | RISK | Portfolio & Risk | 34, 35, 37, 38, 40 | High |
| **AG-12** | PM | Portfolio & Risk | 36, 39 | Mid |
| **AG-13** | TRADE | Trading Operations | 41–47 (all seven) | Mid |
| **AG-14** | AUDIT | Audit & Governance | 48–53 (all six) | Mid |
| **AG-15** | KNOW | Knowledge & Memory | 54–59 (all six) | Mid |
| **AG-16** | INFRA | Infrastructure | 60–65 (all six) | Low |
| **AG-17** | GOV | Institutional Governance | 66–76 (all eleven) | Mixed |

Seventeen agents, one desk (CRYPTO), seventy-six charters covered, zero gaps.

The company is recognisably itself on day one: an Executive that sets missions,
Intelligence that observes, Research that experiments, a Strategy Lab that
builds and attacks, Risk that can veto, Trading that only paper-trades, Audit
that challenges everyone, Knowledge that remembers, Infrastructure that keeps
it running, and Governance that makes cheating impossible.

Then it grows.

---

## 6. Role fission — how the company builds itself

This is the growth mechanism, and it is the answer to "start with sixteen, end
with forty, then hundreds."

### 6.1 The idea

Every agent's record carries:

```
charter    the full remit of its role(s)
coverage   the charter areas this agent currently holds
load       measured: queue depth, latency, tasks/day, backlog age
quality    measured: calibration, replication survival, objection hit rate,
           audit findings against it, cost per accepted output
```

When load or quality metrics cross a declared threshold in a coverage area,
the **Org Development Lead** proposes a **fission**: split the coverage set,
hire a specialist for the split-off part, and hand over.

```
        AG-04 INTEL                          AG-04 INTEL
   holds charters 7–15          ──▶     holds 7, 11, 12, 13
   backlog: 34 tasks                          +
   news latency: 19h                    AG-18 NEWS  (charters 9, 10, 15)
                                        AG-19 FUND  (charters 8, 14)
```

The reverse — **fusion** — merges two agents whose outputs overlap above a
measured threshold, or whose combined load no longer justifies two.

### 6.2 Triggers

Fission and fusion are proposed on **measurement**, never on a hunch:

| Trigger | Threshold example | Proposal |
|---|---|---|
| Backlog depth | > 20 open tasks in one coverage area for 7 days | Fission |
| Response latency | Briefing older than the decision that needs it | Fission |
| Quality degradation | Calibration falling across a coverage area | Fission or retrain |
| Coverage starvation | A charter area with zero outputs in 30 days | Fission or explicit closure |
| New desk opened | Desk has no staff for a department | Hire (role, desk) |
| Output overlap | Two agents' artifacts > 80% duplicative | Fusion |
| Underuse | An agent with < 5 tasks in 30 days | Fusion or suspension |
| Scenario failure | An agent fails the training suite for its charter | Retrain, reassign, or suspend |

### 6.3 The procedure

```
1. Org Development Lead detects a trigger and assembles the evidence
2. Writes an OrgChange proposal: kind, affected charters, justification,
   expected effect, and how the effect will be measured
3. Board or Executive meeting debates and decides
4. On approval:
     - new Agent row is created with the split coverage
     - handover: open tasks, channel membership, memory scope transfer
     - the new agent runs the training scenario suite for its charters
     - its starting record is its scenario performance
5. Effect is measured after a declared window
6. Result is recorded — including when the split made nothing better
```

Step 6 matters. Every org change is an experiment with a predicted outcome, and
the company keeps the record of which ones worked.

### 6.4 The growth path

| Stage | Agents | Desks | Shape |
|---|---|---|---|
| **Launch** | 17 | CRYPTO | Generalists; every charter covered |
| **Stage 2** | ~28 | + EQUITIES | Intelligence splits into 3–4; Research splits statistical/backtest/ML; Audit splits research/data/backtest |
| **Stage 3** | ~45 | + OPTIONS, FUTURES | Most charters held by a dedicated agent; desk-specific analysts and researchers |
| **Stage 4** | ~80 | + FX, COMMODITIES, MEMECOINS | Full roster per active desk; teams per desk; multiple researchers per programme |
| **Stage 5** | 100+ | all seven | Multiple agents per charter per desk where load justifies: 4 researchers, 2 fundamental analysts, 3 critics |

Stage 5 is the `CLAUDE.md` §16 target — "4 researchers, 2 fundamental
analysts" — reached by measurement rather than by decree.

**Nothing in the runtime changes across those stages.** Agents are rows; roles
are charters; desks are configs. Growth is data.

---

## 7. Teams

A **Team** is a durable group with a lead, a charter, and usually a desk.
Missions assign teams, not only individuals.

```
Team:
    team_id · name · department · desk
    lead_agent · members[]
    charter · standing_channels[]
    active_projects[] · metrics
```

Examples at Stage 3: `TEAM-CRYPTO-MOMENTUM`, `TEAM-OPTIONS-VOL`,
`TEAM-EQUITY-FACTORS`, `TEAM-INTEGRITY`.

Teams hold their own standups and their own retrospectives. A team's output
quality is a measured property, and consistently unproductive teams are
dissolved by the same `OrgChange` mechanism that created them.

---

## 8. Permissions — three scopes

Every agent's permissions resolve to three scopes, all enforced in the runtime
and, where it matters, in the database.

### Read scope (what it can see)

A view registry, as in `CLAUDE.md` §3. Widening what a role can see requires
registering a view — so "what did the Strategy Critic know when it approved
this?" is answered by reading a registry, not by tracing calls.

Examples: a Researcher sees the hypothesis, the data spec, and prior findings —
not the sealed out-of-sample window. A Trader sees approved instructions and
market state — not research in progress. An Auditor sees everything, which is
what makes it an auditor.

### Write scope (what it can create or change)

| Entity | Who may write |
|---|---|
| Hypothesis | Researchers, Strategy Lab |
| Registration (locked) | Registrar only |
| Run / metrics | Engines only — **no agent** |
| Finding / interpretation | Analysts, Researchers |
| Objection | Critics, Adversarial, Auditors, Skeptic-in-Residence |
| Strategy version | Strategy Architect proposes; Head of Strategy promotes |
| Risk assessment | Risk roles only — **no other agent, ever** |
| Trade approval | Trade Approval Agent, requires a risk assessment |
| Order | Execution Agent only, requires an approval |
| Org change | Org Development Lead proposes; Board decides |
| Event ledger | Append-only — **no agent** |

The three that carry the most weight: **agents never write numbers**, **only
Risk writes risk**, and **execution requires an unbroken approval chain**.

### Tool scope (what it can invoke)

Bound per agent from its role and desk. A Crypto Technical Analyst has
`engine.backtest.crypto` and `data.ohlcv`; it does not have
`broker.submit`. Tool calls are logged with inputs, outputs, cost and duration.

---

## 9. Skills

Three layers, all versioned, so "skill" is never an unversioned prompt
fragment.

### Capability — deterministic, tested software

`stats.deflated_sharpe@2` · `integrity.leak_scan@1` · `research.purged_cv@1` ·
`portfolio.factor_attribution@1` · `options.implied_vol_surface@1` ·
`futures.roll_yield@1` · `stats.calibration@1`

Versions are immutable. Results name the version that produced them, so a
capability change cannot silently restate history.

### Competence — a role's right to see and duty to produce

`(role, view_id, output_schema, validators[], capabilities[])`

Granting a competence widens a view and extends an output contract. It is a
registry change with a test, not a prompt edit.

### Playbook — a reusable procedure, LLM-facing

The thing that feels most like a "skill" to a human: a written, versioned,
tested procedure an agent follows.

```
playbook: research.test_cross_sectional_signal@3
  when to use · required inputs · steps · required checks
  common failure modes · what disqualifies the result
  worked example · scenario suite that validates it
```

Playbooks are **tested against the synthetic scenario suite**. A playbook
revision that lowers the catch rate on planted defects fails CI and does not
ship. That is what makes them skills rather than folklore.

Skill categories mirror `CLAUDE.md` §5: general, market intelligence,
quantitative research, strategy, risk, trading operations — with per-desk
variants where the procedure genuinely differs (testing an options signal is
not testing a crypto momentum signal).

---

## 10. Careers — agent lifecycle

Agents have histories, and the history is used.

```
HIRED ──▶ ONBOARDING ──▶ ACTIVE ──▶ SENIOR ──▶ LEAD ──▶ DIRECTOR
              │             │  │
              │             │  └──▶ RETRAINING ──▶ ACTIVE
              │             └─────▶ SUSPENDED ──▶ REASSIGNED | RETIRED
              └──▶ FAILED_ONBOARDING ──▶ RETIRED
```

- **Onboarding** runs the training scenario suite for the agent's charters. An
  agent that cannot catch planted defects in its own specialty does not start
  work — a trigger on `agents` refuses the move to `active`, so the ordinary
  activation path cannot get around it; the failure is recorded and the role's
  playbook is reviewed. A third verdict, `not_scored`, covers a charter the
  suite has no fair question for, and it is **never** read as a pass: most of
  the launch roster holds it, and inventing a specialty for every charter so
  nobody had a blank record would put fiction in two thirds of the company's
  permanent record.
- **Promotion** follows measured quality: calibration, findings that survive
  replication, objections upheld, low audit findings. Promotion raises model
  tier, which is how cost follows demonstrated value.
- **Suspension** follows measured failure: repeated role-boundary violations,
  fabricated figures, persistently poor calibration.
- **Retirement** preserves the record. A retired agent's outputs, evidence and
  history remain in the ledger permanently.

Agent performance is **never evaluated on P&L**. A researcher who correctly
kills a bad strategy has produced valuable work, and the metrics say so.

---

## 11. What each department actually does in a day

Concrete, so the design is checkable against reality.

**Market Intelligence** — scheduled scans per desk; posts briefings to desk
channels; flags anomalies as `LEAD` nodes (never findings); answers questions
from Research; maintains source reliability records.

**Quantitative Research** — takes questions from the Research Director and from
Kickoff meetings; forms hypotheses; preregisters through the Registrar; builds
specs; runs engines; reports results with artifact hashes; defends findings in
Research Review meetings.

**Strategy Laboratory** — turns surviving findings into strategy designs;
Discovery searches systematically; Synthesizer combines; Critic and Adversarial
attack; Replication and Robustness test; Validation runs promotion gates and
requests the out-of-sample query.

**Portfolio & Risk** — assesses every proposal; sets and enforces limits;
analyses correlation and exposure; allocates capital; runs stress tests; vetoes.

**Trading Operations** — evaluates setups; plans trades; checks the approval
chain; submits to the paper broker; monitors positions; attributes slippage and
reports the backtest-vs-live gap.

**Audit & Governance** — independently samples and challenges research, data,
backtests, executions and agent behaviour; raises findings that any agent must
answer; reports to the Board.

**Knowledge & Memory** — records lessons; curates the graph; keeps registries;
answers "have we tried this before?" — which is one of the most valuable
questions in the company and currently costs 174 trials' worth of context to
answer by hand.

**Infrastructure** — data freshness, job health, agent liveness, alerting.

**Institutional Governance** — locks registrations, holds sealed data, scores
forecasts, verifies the chain, enforces budgets, and files integrity findings.

**Executive** — sets missions, arbitrates escalations, chairs meetings, and
develops the organization.
