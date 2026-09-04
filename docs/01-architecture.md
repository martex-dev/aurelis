# 01 — System Architecture

Date: 2026-09-04
Status: proposal, v2. Supersedes the v1 draft.

Aurelis is a **corporation**. Not a pipeline, not a framework, not a trading
bot. The software's job is to make a company of AI agents actually function:
give them departments, desks, teams, roles, colleagues, meetings, tools,
memory, budgets, careers, and a building to work in.

Two existing systems are **dependencies, not the system**:

- **martex-quant** is a *tool* inside the Quantitative Research department's
  toolbox — one backtest engine among several, plus a validated crypto data
  lake and a statistics library. It supports researchers; it does not replace
  them.
- **nullius** contributes *core platform patterns* (event ledger, hash chains,
  preregistration triggers, budget accounting) and staffs **one department** —
  Institutional Governance — whose eleven officers **serve** the other
  departments. They do not run the company and they do not replace anyone.

Everything else is Aurelis's own architecture.

---

## 1. The shape of the company

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         MISSION CONTROL STATION                            │
│              the building · every room · every agent · live                │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴─────────────────────────────────────────┐
│                            APPLICATION API                                 │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴─────────────────────────────────────────┐
│                          THE CORPORATION                                   │
│                                                                            │
│  EXECUTIVE ── missions, priorities, org development, the Chair             │
│      │                                                                     │
│      ├── MARKET INTELLIGENCE ──┐                                           │
│      ├── QUANTITATIVE RESEARCH ┤                                           │
│      ├── STRATEGY LABORATORY ──┤   × 7 MARKET DESKS                        │
│      ├── PORTFOLIO & RISK ─────┤   crypto · equities · options · futures   │
│      ├── TRADING OPERATIONS ───┤   commodities · FX · memecoins            │
│      ├── AUDIT & GOVERNANCE ───┤                                           │
│      ├── KNOWLEDGE & MEMORY ───┘                                           │
│      ├── INFRASTRUCTURE                                                    │
│      └── INSTITUTIONAL GOVERNANCE  ← nullius's 11 officers, in service     │
│                                                                            │
│  Agents work individually · Teams work together · Meetings decide          │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴─────────────────────────────────────────┐
│                         THE AGENT RUNTIME                                  │
│   agents · tools · channels · meetings · missions · tasks · memory         │
│   permissions · budgets · scheduling · model routing                       │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴─────────────────────────────────────────┐
│                       ENGINES & DATA (the tools)                           │
│                                                                            │
│   martex-quant ── crypto backtests, data lake, statistics                  │
│   equities engine · options engine · futures engine · FX engine            │
│   synthetic engine ── training scenarios with known answers                │
│   data sources ── prices, fundamentals, news, filings, sentiment, on-chain │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │
┌──────────────────────────────────┴─────────────────────────────────────────┐
│                      PORTFOLIO → RISK → APPROVAL → EXECUTION               │
│              BacktestBroker · SimulationBroker · PaperBroker               │
│                    LiveBroker — absent during development                  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Repository layout

New repository. Depends on `martex-quant` (PyPI) and `nullius` (git dependency).

```
aurelis/
├── core/              identity, ids, config, clock, event types, errors
├── org/               departments, desks, roles, charters, teams, headcount,
│                      fission/fusion, org changes, career state
├── agents/            agent runtime, agent record, contracts, memory,
│                      tool binding, permission resolution, lifecycle
├── comms/             messages, channels, mentions, notifications, escalation
├── meetings/          meeting types, protocols, chair, rounds, minutes,
│                      decisions, action items, productivity metrics
├── missions/          missions, projects, tasks, assignment, dependencies,
│                      progress, budgets
├── research/          hypotheses, experiments, evidence, findings, critique,
│                      replication, the research lifecycle state machine
├── intel/             observations, signals, briefings, source registry,
│                      freshness and calibration tracking
├── engines/           adapter layer over every compute engine
│   ├── martex/        crypto backtest + stats + data lake adapter
│   ├── equities/      · options/ · futures/ · fx/ · commodities/
│   └── synthetic/     training scenarios with known answers
├── strategy/          strategy registry, versions, lifecycle, promotion gates
├── portfolio/         construction, allocation, interaction analysis
├── risk/              policies, assessments, limits, veto, kill switches
├── trading/           proposals, approvals, brokers, positions, post-trade
├── governance/        nullius integration: preregistration, custody, evidence
│                      typing, forecast scoring, audit officers
├── memory/            institutional memory, knowledge graph, lessons, vault
├── skills/            capabilities, competences, playbooks, registry
├── station/           Mission Control: layout, rooms, views, live feed
├── platform/          db, migrations, queue, scheduler, llm, budget,
│                      observability, cache, artifacts, sandbox
└── cli/               aurelis <command>
```

Nine architectural layers, each with a stable boundary. The rule that keeps it
navigable: **a module may import from layers below it and from `core`, never
from layers above.**

```
station · cli
    ↓
missions · meetings · comms
    ↓
org · agents · research · strategy · portfolio · risk · trading · intel
    ↓
skills · engines · governance · memory
    ↓
platform · core
```

---

## 3. The agent runtime

An agent is a **row**, not a class. That is what lets the company go from 16 to
40 to 400 without touching the runtime.

```python
Agent:
    agent_id        "AG-0042"
    name            "TA-3"                  # what colleagues call it
    role            TECHNICAL_ANALYST       # from the role registry
    department      MARKET_INTELLIGENCE
    desk            OPTIONS | None          # market specialisation
    team            "TEAM-VOL-STRUCTURE"
    seniority       JUNIOR | SENIOR | LEAD | DIRECTOR
    charter         the role's full remit
    coverage        the subset of the charter THIS agent currently holds
    skills          [competence@version, ...]
    playbooks       [playbook@version, ...]
    tools           [tool_id, ...]
    channels        [channel_id, ...]
    permissions     resolved: read_scope, write_scope, tool_scope
    model_policy    tier + routing + max effort
    budget          daily allowance in the cost ledger
    memory          agent-scoped store + institutional access scope
    metrics         calibration · throughput · quality · cost · usefulness
    state           IDLE | WORKING | IN_MEETING | BLOCKED | SUSPENDED
    hired_at        · promoted_at · suspended_at
```

### The loop

Each agent is driven by a worker that repeats:

```
1.  wake        (task assigned · meeting starting · schedule · mention)
2.  orient      build the agent's VIEW — its permissions decide what it sees
3.  recall      pull relevant institutional memory + own memory
4.  act         reason, then either produce an artifact or call a tool
5.  record      artifact + events + cost, in one transaction
6.  communicate post to channels, answer mentions, raise escalations
7.  sleep
```

Steps 2 and 5 are where the invariants live. An agent cannot see outside its
resolved read scope and cannot write outside its write scope, because the
runtime builds the view and the database refuses the row.

### Tools

A tool is a **bound capability**: a deterministic function the agent may call,
with a declared cost class and a recorded invocation.

```
tool:engine.backtest.crypto        → martex-quant run_backtest
tool:engine.backtest.equities      → equities engine
tool:engine.options.price          → options engine (greeks, IV surface)
tool:data.ohlcv / fundamentals / news / filings / onchain / sentiment
tool:stats.deflated_sharpe / bootstrap / cointegration / purged_cv
tool:integrity.leak_scan / point_in_time_check
tool:portfolio.factor_attribution / correlation_matrix
tool:memory.search / graph.walk / ledger.query
tool:comms.post / mention / escalate / call_meeting
```

Tool calls are logged with inputs, outputs, cost and duration. "What did this
agent actually do today?" is a query, not an investigation.

### Spawning agents

Hiring is an org action, recorded with justification:

```
OrgChange(kind=HIRE, role=..., desk=..., justification=..., evidence=[...],
          decided_by=<meeting>, decided_at=...)
```

The Org Development Lead proposes; a Board or Executive meeting decides. See
`docs/02-organization.md` §6 for the growth mechanism.

---

## 4. Communication

Agents genuinely talk to each other. Three mechanisms, in increasing weight:

| Mechanism | Cost | Use |
|---|---|---|
| **Message** | cheap | Direct, addressed, typed. Question, answer, request, evidence, warning. |
| **Channel post** | cheap | Broadcast to a department, desk, team, or mission. Briefings, findings, alerts. |
| **Meeting** | expensive | Synchronous, multi-round, transcript kept. Brainstorming, debate, decisions. |

### Message

```
Message:
    message_id · from_agent · to[] · cc[]
    channel · department · desk
    mission_id · project_id · hypothesis_id · strategy_id
    type      OBSERVATION | QUESTION | ANSWER | REQUEST | PROPOSAL | CRITIQUE
              | EVIDENCE | WARNING | DECISION | ESCALATION | APPROVAL
              | REJECTION | MEETING_INVITE | MEETING_SUMMARY | HANDOFF
    priority  LOW | NORMAL | HIGH | URGENT
    subject · body
    evidence_refs[]        artifact hashes, findings, experiments
    requires_response · respond_by
    thread_id · in_reply_to
```

Every factual assertion in a message body should carry an evidence ref or be
marked as opinion. That is a validator, not a request.

### Channels

Auto-created and durable: one per department, per desk, per team, per mission,
plus company-wide `#all-hands`, `#alerts`, `#findings`, `#graveyard`.

An agent's channel membership is part of its record, and reading a channel it
does not belong to is a permission error.

### Escalation

Unresolved disagreement, blocked work, or a critical finding escalates up the
chain: agent → team lead → department head → Executive. Escalation creates a
`Task` for the receiver and, above a threshold, calls a meeting.

Meetings get their own document: `docs/03-meetings.md`.

---

## 5. Missions, projects, tasks

Three levels, so a company-scale objective decomposes without one giant plan.

```
MISSION            "Find durable cross-asset carry premia"
  objective · scope · priority · owner · departments[] · desks[]
  budget · deadline · status · progress · outputs · decisions

  └── PROJECT      "Options-desk variance risk premium study"
        lead · team · hypotheses[] · deliverables · budget · status

        └── TASK   "Backtest VRP on SPX 2015-2026 with realistic spreads"
              assignee · type · inputs · expected_artifact · allowance
              status · blockers · result
```

Missions are opened by the Executive, usually out of a Board meeting. Projects
are opened by department heads. Tasks are created by team leads, by meetings
(as action items), and by the scheduler.

Every mission begins with a **Kickoff meeting** and ends with a
**Retrospective meeting**. That is a rule of the mission state machine, not a
convention.

---

## 6. Market desks — the second dimension

The company covers every market the user named. Desks are the specialisation
axis that crosses departments.

| Desk | Instruments | Primary engines | Data |
|---|---|---|---|
| **CRYPTO** | spot, perpetuals, funding, basis | martex-quant | ccxt/Binance lake, on-chain |
| **EQUITIES** | single names, ETFs, indices | equities engine | prices, fundamentals, filings, factors |
| **OPTIONS** | listed options, vol surfaces | options engine | chains, IV, greeks, term structure |
| **FUTURES** | index, rates, term structure | futures engine | continuous contracts, roll calendars |
| **COMMODITIES** | energy, metals, agriculture | futures engine | spot, futures curves, inventories |
| **FX** | majors, crosses, carry | fx engine | tick/bar, rate differentials |
| **MEMECOINS** | micro-cap tokens, launches | martex-quant `meme/` | DexScreener, GeckoTerminal, wallets |

An agent is `(role, desk)`. A Technical Analyst on the Options desk and one on
the FX desk are different agents with the same charter and different tools,
data and playbooks. **This is how the company reaches hundreds of agents
naturally** — seven desks × the role roster, opened as evidence justifies.

### The existing tools map onto the desks

The nine projects under `Desktop/projects/` are not scraps — they are desk
capabilities waiting to be wrapped:

| Tool | Desk | Becomes |
|---|---|---|
| `vol-surface`, `implied-move` | OPTIONS | `tool:engine.options.surface`, `tool:intel.implied_move` |
| `roll-yield` | FUTURES, COMMODITIES | `tool:engine.futures.roll_cost` |
| `factor-exposure` | EQUITIES | `tool:portfolio.factor_attribution` |
| `purged-cv`, `timeleak`, `leakguard`, `cv-visualizer` | ALL | `tool:integrity.*` |
| `calibrate` | ALL | `tool:stats.calibration` |

### Adding a desk

Register a `DeskConfig` — instruments, calendar, data sources, engines, cost
model, constraints, risk limits — and staff it. No architectural change. That
is the whole point of the desk abstraction.

---

## 7. Engines — the tool layer

`engines/` is an adapter layer with one job: give agents a uniform way to run
computation across very different markets.

```python
class ResearchEngine(Protocol):
    def universe(self, spec: UniverseSpec) -> Universe: ...
    def data(self, spec: DataSpec) -> Panel: ...
    def features(self, spec: FeatureSpec, panel: Panel) -> Panel: ...
    def backtest(self, spec: BacktestSpec) -> RunArtifact: ...
    def statistics(self, spec: StatSpec, run: RunArtifact) -> MetricSet: ...
    def capabilities(self) -> EngineCapabilities: ...
```

`capabilities()` matters: the Options engine supports greeks and the crypto
engine does not, and an agent asking for something an engine cannot do gets a
typed refusal rather than a wrong number.

**The martex adapter** wraps `run_backtest`, `run_multi_backtest`, the Parquet
lake, `stats/`, and the walk-forward harness. Aurelis calls it in a
**subprocess with an explicit workspace** — martex-quant `chdir`s into its
workspace, so in-process calls would make Aurelis's own paths depend on
whatever experiment ran last.

**The synthetic engine** generates market scenarios with a *known* answer —
planted momentum premia, planted leaks, planted regime effects, and scenarios
with nothing in them. Used for two things: training and scoring new agents
before they touch real research, and measuring whether an org change actually
improved anything. See §9.

**Engines are extended, not replaced.** martex-quant covers crypto well. It
covers options not at all. Aurelis builds what is missing and adapts what
exists.

---

## 8. How research actually flows

The full lifecycle from `CLAUDE.md` §8, with the human-scale version of who
does what. Detail in `docs/05-lifecycles.md`.

```
OBSERVE          Market Intelligence agents watch their desks, post briefings
QUESTION         Research Director + Kickoff meeting choose what to study
HYPOTHESIZE      Researchers propose; Strategy Lab brainstorms in meeting
PREREGISTER      Governance registrar locks the spec and hashes it
DESIGN           Quant researchers + Research Engineer build the experiment
RUN              Engines execute; agents do not compute numbers
ANALYZE          Statistical Researcher computes; Analysts interpret
CRITIQUE         Strategy Critic + Adversarial Researcher attack it
                 ↳ Research Review meeting when contested
REPLICATE        Replication Researcher re-tests with a deliberate variation
ROBUSTNESS       Robustness Researcher stresses it
OUT-OF-SAMPLE    Custodian releases a counted query against sealed data
PORTFOLIO TEST   Correlation + Exposure Analysts test interaction with the book
REVIEW           Strategy Committee meeting decides promotion
PAPER DEPLOY     Trading Operations activates it under Risk's limits
MONITOR          Position Monitor + Post-Trade Analyst track the live gap
REVIEW           Retrospective meeting → lessons → institutional memory
```

Two rules hold across all of it:

1. **Agents never compute the numbers.** Every metric comes from an engine or a
   capability, and carries the artifact hash it was read from. An agent that
   states a figure it did not receive from a tool fails validation.
2. **Every conclusion traces to evidence.** Findings carry evidence refs;
   evidence carries artifact hashes; artifacts carry the spec, seed, data
   fingerprint and code version that produced them.

Those two rules are what make a company of LLMs a research organization rather
than a very expensive opinion generator.

---

## 9. The company improves itself

This is core, and it stays core. Three mechanisms, all measured.

### 9.1 Agent performance

Every agent accumulates a record, and none of it is P&L:

| Role family | Measured by |
|---|---|
| Analyst | evidence quality, freshness, **forecast calibration**, useful observations |
| Researcher | reproducibility, hypotheses that survive, replication success, cost per accepted finding |
| Critic | objections upheld, defects caught, false-alarm rate |
| Risk | violations prevented, false positives, decision quality |
| Trader | execution quality, adherence to approved instructions |
| Chair | meeting productivity — decisions and state changes per meeting |

**Forecast calibration is the backbone.** Before any experiment runs, every
participating agent records a probability for the outcome. Afterwards the
forecast is scored. Over hundreds of experiments this gives a per-agent quality
signal that costs one cheap call each and does not require anyone to grade
anyone's prose.

### 9.2 Training scenarios — how we know an agent or an org change is good

The synthetic engine produces research scenarios where **the answer is known
in advance**: a planted momentum premium of a stated size, a planted data leak,
a planted regime dependency, or nothing at all.

Uses:

- **Onboarding.** A newly hired agent runs training scenarios before it touches
  live research. Its hit rate and false-positive rate become its starting
  record.
- **Org experiments.** Does adding an Adversarial Researcher reduce false
  discoveries? Run the same scenario set with and without, and count. Does 3
  technical analysts beat 2? Same method.
- **Regression.** When a playbook or capability changes, the scenario suite
  re-runs. A change that lowers the catch rate is caught before it reaches real
  research.

This is how "the company researches itself" becomes arithmetic instead of
opinion. It needs no market data and runs offline, cheaply.

### 9.3 Organizational development

The **Org Development Lead** (Executive) watches measured triggers and proposes
structural changes:

| Trigger | Proposal |
|---|---|
| Backlog / latency in a coverage area | Split the role (fission) — hire a specialist |
| Two agents' outputs overlap above threshold | Merge (fusion) |
| A desk is never studied | Staff it, or close it and say why |
| An agent's calibration is persistently poor | Retrain on scenarios, reassign, or suspend |
| A meeting type produces no state changes | Change its protocol or stop holding it |
| A playbook underperforms on scenarios | Revise it, versioned |

Every proposal goes to a Board meeting, carries evidence, and is recorded as an
`OrgChange`. The company's structure has a version history exactly like a
strategy does.

---

## 10. Risk, portfolio and the trading boundary

Independent authority, enforced structurally.

```
Strategy signals
      ↓
Signal aggregation                 Strategy Lab
      ↓
Portfolio construction             Portfolio Manager + Capital Allocation
      ↓
Risk assessment                    Risk Manager — INDEPENDENT VETO
      ↓
Trade approval                     Trade Approval Agent
      ↓
Execution                          Execution Agent → BrokerAdapter
```

Three numbers are persisted on every proposal, always:

```
desired_exposure     what the strategy asked for
allowed_exposure     what Risk permitted
final_target         what portfolio construction settled on
```

A `TradeProposal` without a matching `RiskAssessment` cannot become a
`TradeApproval` — foreign key plus trigger. Risk may allow, shrink, veto, halt,
or suspend a strategy, and every decision is recorded including the ones that
change nothing.

### Brokers

```python
class BrokerAdapter(Protocol):
    def submit(self, order) -> OrderAck
    def positions(self) -> list[Position]
    def equity(self) -> float
    def flatten_all(self) -> None
```

`BacktestBroker` · `SimulationBroker` · `PaperBroker` are implemented.
**`LiveBroker` is not written during development** (ADR-0006). `Portfolio.mode`
has no `LIVE` member. Aurelis creates no path to martex-quant's MT5 adapter,
and a test asserts no module imports it.

---

## 11. Platform

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | The whole ecosystem, both dependencies |
| Persistence | SQLAlchemy → SQLite dev, Postgres when concurrency demands | No server to start; one URL to change |
| Migrations | Alembic | State is durable from day one |
| Queue | Database-backed, same transaction as the event ledger | A task's completion and the events describing it must commit together |
| Scheduler | APScheduler-style in-process, DB-persisted jobs | Briefings, monitors, standups, data pulls |
| Agent framework | **None.** Aurelis's own runtime | The control flow is where every permission and budget check lives |
| LLM access | Provider abstraction — see §12 | Subscription first, API later |
| Artifacts | Content-addressed store | Hashes are the provenance mechanism |
| Sandbox | Subprocess with resource limits; Docker before any code generation | Engines run isolated |
| Real-time | FastAPI + SSE | Traffic is server → client |
| Station | Generated SVG/HTML + light interactive shell | Vector only, no binary assets |
| Data | martex-quant Parquet lake for crypto; per-desk stores alongside | Reuse what is validated |

---

## 12. Cost, and running on a Claude Pro subscription

The company must be cheap to run right now. This shapes the LLM layer.

### The provider abstraction

```python
class ModelProvider(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse
    def cost(self, usage: Usage) -> Decimal
```

Implementations:

| Provider | Use |
|---|---|
| `agent_sdk` | Claude Agent SDK against the **Pro subscription** — the default while there is no budget |
| `anthropic_api` | Direct API with per-token accounting — enabled when a budget exists |
| `cache` | Wraps either. Keyed on pinned model version + prompt hash |
| `mock` | Deterministic replay for tests and for running the whole company offline |

Switching providers is a config change. Nothing above the provider layer knows
which is active. The cost ledger records units in both tokens and money so the
accounting works either way.

### The cost rules

The dominant cost is meetings and analyst chatter, so the controls are aimed
there:

1. **Deterministic first.** Statistics, backtests, data validation, screening,
   ranking, correlation, portfolio math — all software. LLMs do interpretation,
   generation, critique, planning, and conversation. This is the single largest
   lever by an order of magnitude.
2. **Tiered models.**

   | Tier | Model | Roles |
   |---|---|---|
   | High | Opus | Company Manager, Research Director, Strategy Architect, Theorist-grade research |
   | Mid | Sonnet | Analysts, researchers, critics, reviewers, risk |
   | Low | Haiku | Status turns, forecasts, summarisation, routing, monitors, routine briefings |
   | None | — | Every deterministic officer: registrar, custodian, schedulers, auditors' mechanical checks |

3. **Meeting budgets.** Every meeting declares a token budget and a round cap
   before it starts, and the Chair enforces both. See `docs/03-meetings.md` §6.
4. **Thin views.** An agent's prompt is its view, and views are small because
   permissions make them small.
5. **Structured outputs.** Schema-constrained, so prose is not paid for twice.
6. **Caching and replay.** Pinned model versions make responses reusable and
   whole company-days replayable offline.
7. **Deduplication.** Spec hash + data fingerprint: if the experiment ran,
   return the artifact.
8. **Hard budgets.** Per agent per day, per project, per mission, per company.
   Refused at dispatch, before the call. Exhaustion is a recorded outcome.
9. **Idle is free.** Agents are event-driven. A department with nothing to do
   costs nothing.

---

## 13. Safety

1. **No live execution** during development. Not disabled — absent.
2. **Agents never author executing code.** Experiments are specifications
   naming registered operations; the engine layer compiles and runs them. Code
   generation stays gated on a Docker sandbox.
3. **Risk is unbypassable.** Enforced by foreign key and trigger, not by role
   instruction.
4. **Append-only, hash-chained ledger.** Edits are detectable at a named
   sequence number.
5. **Hard money budgets** refused at dispatch.
6. **Secrets never enter an agent view.** Credentials live in the platform
   layer and are reachable only by deterministic integrations.
7. **Sealed data.** The Custodian holds out-of-sample windows in a separate
   process with a counted query budget.

---

## 14. Testing

| Category | Asserts |
|---|---|
| Unit | Every capability, engine adapter, and org rule |
| Invariant | Every trigger fires against raw SQL, not only through the ORM |
| Permission | An agent cannot read outside its view or write outside its scope |
| Meeting | Protocols terminate, budgets bind, minutes extract, dissent survives |
| Org | Fission/fusion preserve total coverage; no charter area is orphaned |
| Determinism | Same spec + seed + data fingerprint → identical artifact hash |
| Scenario | The synthetic suite: planted effects caught, nulls not over-claimed |
| Golden | Known martex-quant results reproduce (H71's incumbent arm, Sharpe 1.47) |
| Failure | Model refusal, malformed output, timeout, OOM, data outage, budget exhaustion, agent crash mid-meeting |
| End-to-end | Mission → kickoff → research → critique → meeting → decision → strategy → risk → paper → retrospective → memory |

---

## 15. Observability

Everything flows through the event ledger; observability is projection.

Tracked: agent state, task state, mission and project state, meeting outcomes,
model calls, tool calls, engine runs, errors, latency, token and money spend,
research outcomes, decisions, execution events, alerts, org changes.

Raw logs stay an implementation detail. Mission Control turns them into the
company timeline, the agent activity views, and the department dashboards.

---

## 16. Where the two dependencies actually sit

Stated plainly, because it matters:

**martex-quant** is called by `engines/martex/`. It provides crypto backtests,
a validated data lake, statistics, and a prop-firm simulator. It is roughly
**one desk's worth of engine plus a shared statistics library**. It does not
generate hypotheses, does not decide anything, does not talk, and is invisible
to every agent except through tool calls.

**nullius** contributes two things. First, platform patterns Aurelis
implements in its own `platform/` and `governance/`: the hash-chained event
ledger, preregistration-before-run enforced by trigger, evidence typing,
hierarchical money budgets, forecast scoring. Second, the **Institutional
Governance department** — eleven officers who serve the company: they lock
registrations, hold sealed data, type evidence, score forecasts, verify the
chain, and keep the budget ledger. They have no authority over research
direction and they replace nobody.

Everything else — the corporation, the departments, the desks, the meetings,
the missions, the agents, the station — is Aurelis.
