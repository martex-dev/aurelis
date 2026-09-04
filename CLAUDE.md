CLAUDE.md --- Autonomous Quant Corporation
name: Aurelis
===

## 0\. Mission

You are working on an ambitious project whose goal is to build an
**AI-native quantitative research and trading corporation**.

This is NOT a normal trading bot and NOT merely a collection of AI
agents.

The target system is a persistent organization of specialized AI agents
that can:

1. observe markets and external information,
2. generate and investigate hypotheses,
3. perform quantitative research,
4. backtest and stress-test ideas,
5. debate and critique findings,
6. replicate promising research,
7. construct and refine systematic strategies,
8. evaluate portfolio-level interactions,
9. manage risk,
10. paper-trade validated strategies,
11. monitor live/paper performance,
12. learn from outcomes,
13. improve its research process and organizational structure,
14. preserve a permanent, auditable institutional memory,
15. and expose the entire organization through a visual **Mission
Control / Research Lab station**.

The ultimate ambition is to create a functioning autonomous quantitative
organization. Profitability is an objective to investigate and earn
through evidence, NOT an assumption.

The system must be designed so that it can honestly conclude that a
hypothesis or strategy failed.

\---

# 1\. Core Philosophy

## 1.1 The company is the product

Do not think of this project as:

> "A group of LLMs that generate trading signals."

Think of it as:

> "A quantitative research company whose employees are autonomous AI
> agents."

The system therefore needs:

* departments,
* teams,
* roles,
* skills,
* missions,
* research programs,
* meetings,
* memory,
* governance,
* experimentation,
* performance evaluation,
* organizational learning,
* strategy lifecycle management,
* risk management,
* trading operations,
* auditing,
* and a visual headquarters.

\---

## 1.2 Intelligence should emerge from the organization

Do not create one giant super-agent responsible for everything.

Specialization is a core architectural principle.

A researcher should not automatically be allowed to trade.

A market-intelligence agent should provide evidence, not make portfolio
decisions.

A strategy researcher should propose and test hypotheses, not bypass
validation.

A trader should execute approved portfolio instructions, not invent a
new strategy.

A risk manager must be able to veto or modify exposure.

An auditor must be independent enough to challenge the organization.

\---

## 1.3 Evidence beats persuasion

Agents must never win research decisions because they sound convincing.

Research decisions should be grounded in:

* data,
* reproducible experiments,
* statistical evidence,
* out-of-sample performance,
* robustness,
* transaction costs,
* realistic execution assumptions,
* regime analysis,
* replication,
* and adversarial review.

LLM reasoning is an orchestration and interpretation layer, not a
substitute for quantitative evidence.

\---

## 1.4 Failed research is valuable

The company must permanently preserve:

* failed hypotheses,
* failed experiments,
* invalidated strategies,
* false discoveries,
* replication failures,
* data problems,
* research warnings,
* and reasons for rejection.

Never optimize the system to make the dashboard look successful.

A researcher that correctly kills a bad strategy has produced valuable
work.

\---

## 1.5 Never assume profitability

The system must never use language such as:

> "This strategy is profitable"

unless the underlying evaluation criteria justify that statement.

Prefer precise states:

* candidate,
* promising,
* inconclusive,
* rejected,
* validated for paper trading,
* paper-trading,
* degraded,
* suspended,
* retired.

The architecture must make it easy to discover that no durable edge
exists.

\---

# 2\. High-Level Organization

The intended organization is approximately:

``` text
AUTONOMOUS QUANT CORPORATION
│
├── EXECUTIVE / MISSION CONTROL
│   ├── CEO / Company Manager
│   ├── CIO / Research Director
│   ├── Operations Director
│   └── Mission Orchestrator
│
├── MARKET INTELLIGENCE
│   ├── Fundamental Analysis
│   ├── News Intelligence
│   ├── Sentiment / Social Intelligence
│   ├── Technical Analysis
│   ├── Macro / Regime Analysis
│   └── Alternative Data
│
├── QUANTITATIVE RESEARCH
│   ├── Hypothesis Research
│   ├── Backtesting
│   ├── Statistical Research
│   ├── ML / Modeling Research
│   ├── Monte Carlo / Simulation
│   └── Research Engineering
│
├── STRATEGY LABORATORY
│   ├── Strategy Discovery
│   ├── Strategy Synthesis
│   ├── Strategy Debate
│   ├── Adversarial Research
│   ├── Replication
│   ├── Robustness Testing
│   └── Strategy Evaluation
│
├── PORTFOLIO \& RISK
│   ├── Risk Management
│   ├── Portfolio Management
│   ├── Exposure Analysis
│   ├── Correlation / Interaction Research
│   └── Capital Allocation
│
├── TRADING OPERATIONS
│   ├── Market Setup Analysis
│   ├── Trade Approval
│   ├── Execution
│   ├── Position Monitoring
│   └── Post-Trade Analysis
│
├── AUDIT \& GOVERNANCE
│   ├── Research Integrity
│   ├── Data Integrity
│   ├── Backtest Audit
│   ├── Execution Audit
│   └── Agent Behavior Audit
│
├── KNOWLEDGE \& MEMORY
│   ├── Institutional Memory
│   ├── Research Archive
│   ├── Strategy Registry
│   ├── Hypothesis Ledger
│   └── Knowledge Graph
│
├── INFRASTRUCTURE
│   ├── Data Systems
│   ├── Compute
│   ├── Scheduling
│   ├── Agent Runtime
│   ├── Observability
│   └── Integrations
│
└── MISSION CONTROL STATION
    ├── Facility Overview
    ├── Department Views
    ├── Agent Views
    ├── Research Views
    ├── Strategy Views
    ├── Portfolio Views
    ├── Risk Views
    ├── Trading Views
    ├── Knowledge Graph
    └── Historical Timeline
```

This is a target organizational model, not a requirement to implement
every department immediately.

\---

# 3\. Agent Model

Agents must be composable.

Conceptually:

``` text
AGENT
├── identity
├── department
├── team
├── role
├── skills\[]
├── permissions\[]
├── objectives\[]
├── memory
├── tools\[]
├── communication channels
├── performance metrics
├── research history
└── current state
```

The distinction is critical:

* **Role = who the agent is**
* **Skill = what capabilities it has**
* **Mission = what it is currently trying to accomplish**
* **Department = organizational context**
* **Permissions = what it is allowed to do**
* **Memory = what it knows from prior work**
* **Tools = what it can actually access**

Do not hard-code all of this into giant agent prompts.

\---

# 4\. Initial Roles

The architecture should support, at minimum:

## Executive

* Company Manager
* Research Director / CIO
* Operations Director
* Mission Orchestrator

## Market Intelligence

* Fundamental Analyst
* News Analyst
* Sentiment Analyst
* Technical Analyst
* Macro Analyst
* Regime Analyst

## Research

* Researcher
* Lead Researcher
* Quant Researcher
* Statistical Researcher
* Backtest Researcher
* Simulation / Monte Carlo Researcher
* ML Researcher
* Research Engineer

## Strategy

* Strategy Architect
* Strategy Synthesizer
* Strategy Critic
* Adversarial Researcher
* Replication Researcher
* Validation Researcher

## Portfolio \& Risk

* Risk Manager
* Portfolio Manager
* Exposure Analyst
* Correlation Analyst
* Capital Allocation Analyst

## Trading

* Market Setup Analyst
* Trade Planner
* Trade Approval Agent
* Execution Agent
* Position Monitor
* Post-Trade Analyst

## Audit

* Research Auditor
* Data Auditor
* Backtest Auditor
* Execution Auditor
* Agent Behavior Auditor

The exact number of agents per role must be configurable and eventually
**experimentally optimized**.

\---

# 5\. Skills Architecture

Skills must be reusable and independent of agent identity.

The system should support importing/adapting useful external skill
definitions while maintaining its own internal skill registry.

Potential skill categories:

### General

* research
* writing
* summarization
* critical thinking
* data analysis
* Python
* statistics
* visualization
* software engineering

### Market Intelligence

* fundamental analysis
* technical analysis
* sentiment analysis
* news analysis
* macro analysis
* market regime detection

### Quantitative Research

* hypothesis design
* backtesting
* statistical testing
* Monte Carlo
* walk-forward analysis
* robustness testing
* factor research
* portfolio analysis
* transaction cost modeling

### Strategy

* strategy design
* signal construction
* signal evaluation
* strategy combination
* strategy decomposition
* adversarial testing
* replication

### Risk

* position sizing
* exposure analysis
* drawdown analysis
* correlation analysis
* portfolio risk
* stress testing

### Trading Operations

* trade planning
* execution analysis
* order validation
* position monitoring
* post-trade review

Skills should have metadata, versioning, tests, and documentation.

\---

# 6\. Agent Communication

Agents must be able to communicate through structured messages rather
than relying only on raw conversational context.

Messages should have concepts such as:

``` text
sender
recipient / recipients
department
mission\_id
research\_program\_id
experiment\_id
strategy\_id
message\_type
priority
timestamp
payload
evidence\_refs\[]
requires\_response
```

Useful message types:

* observation
* hypothesis
* evidence
* question
* critique
* request
* proposal
* experiment\_result
* warning
* decision
* escalation
* meeting\_invitation
* meeting\_summary
* approval
* rejection

Agents should be able to:

* send messages,
* request reviews,
* create research tasks,
* ask another specialist a question,
* invite agents to meetings,
* challenge findings,
* reference previous evidence,
* and escalate unresolved disagreements.

\---

# 7\. Meetings

Meetings are first-class system objects.

A meeting should have:

``` text
meeting\_id
purpose
mission
participants
agenda
discussion
evidence referenced
disagreements
proposals
decisions
action items
owner
deadline
final outcome
```

Meetings must not become pointless roleplay.

Each meeting should produce useful state changes:

* a new experiment,
* a research task,
* a strategy modification,
* a rejection,
* a validation request,
* a risk restriction,
* or a documented decision.

Prefer structured debate over endless conversational loops.

\---

# 8\. Research Lifecycle

The company should operate through a rigorous research lifecycle:

``` text
OBSERVE
  ↓
QUESTION
  ↓
HYPOTHESIZE
  ↓
PREREGISTER
  ↓
DESIGN EXPERIMENT
  ↓
RUN
  ↓
ANALYZE
  ↓
CRITIQUE
  ↓
REPLICATE
  ↓
ROBUSTNESS TEST
  ↓
OUT-OF-SAMPLE TEST
  ↓
PORTFOLIO INTERACTION TEST
  ↓
PAPER DEPLOYMENT
  ↓
MONITOR
  ↓
REVIEW
  ↓
IMPROVE / SUSPEND / RETIRE
```

Every stage must leave an auditable record.

\---

# 9\. Research Integrity

The architecture must explicitly defend against:

* look-ahead bias
* data leakage
* survivorship bias
* selection bias
* overfitting
* parameter mining
* multiple-testing problems
* unrealistic transaction costs
* unrealistic liquidity assumptions
* incorrect timestamps
* bad corporate-action handling
* accidental future information
* contaminated train/test splits
* regime-specific conclusions presented as universal
* cherry-picking successful experiments

Experiments must preserve provenance.

A result should be traceable to:

``` text
data version
data fingerprint
code version
configuration
random seed
experiment definition
model version
environment
execution assumptions
cost assumptions
time period
universe
```

\---

# 10\. Strategy Lifecycle

Strategies are persistent research entities.

Example state machine:

``` text
IDEA
 ↓
CANDIDATE
 ↓
RESEARCHING
 ↓
PROMISING
 ↓
UNDER\_REVIEW
 ↓
VALIDATED
 ↓
PAPER\_TRADING
 ↓
MONITORING
 ↓
DEGRADED
 ↓
SUSPENDED
 ↓
RETIRED
```

A strategy should contain:

* identity
* thesis
* signals
* universe
* timeframe
* entry logic
* exit logic
* sizing logic
* constraints
* risk assumptions
* research evidence
* experiments
* known weaknesses
* validation history
* performance history
* portfolio interactions
* current status
* version history

Strategies must be versioned.

Do not silently modify a strategy after validation.

A modification creates a new version and requires re-evaluation.

\---

# 11\. Portfolio Architecture

Individual strategies must not directly control the entire portfolio.

Conceptually:

``` text
Strategy Signals
      ↓
Signal Aggregation
      ↓
Portfolio Construction
      ↓
Risk Constraints
      ↓
Trade Approval
      ↓
Execution
```

Portfolio-level research must investigate:

* correlation,
* concentration,
* overlapping exposures,
* factor overlap,
* drawdown interaction,
* liquidity,
* leverage,
* turnover,
* strategy capacity,
* regime dependence.

The best individual strategy is not automatically the best portfolio
component.

\---

# 12\. Risk Architecture

Risk must have independent authority.

Risk should be able to:

* reject trades,
* reduce exposure,
* impose limits,
* suspend strategies,
* flag abnormal conditions,
* request review,
* and stop execution.

Risk decisions must be recorded.

The system must distinguish:

``` text
STRATEGY SAYS:
"Desired exposure = X"

RISK SAYS:
"Maximum allowed exposure = Y"

PORTFOLIO SAYS:
"Final target = Z"
```

Execution may only receive the approved result.

\---

# 13\. Trading Safety Boundary

The initial system must default to **simulation / paper trading**.

Real-money execution must not be casually enabled.

Execution architecture should use an abstraction such as:

``` text
BrokerAdapter
├── PaperBroker
├── BacktestBroker
└── LiveBroker (disabled by default)
```

The system should make the difference between:

* backtest,
* simulation,
* paper trading,
* and real execution

explicit.

Do not allow an agent to bypass execution permissions.

Any future live adapter must have explicit configuration,
authentication, risk limits, kill switches, logging, and
human-controlled enablement.

\---

# 14\. Existing Quant Research Integration

The existing `martex-quant` project should be treated as a potential
**quantitative research department / engine**, not automatically
rewritten.

First inspect it thoroughly.

Determine:

* what functionality already exists,
* what can be reused,
* what APIs/interfaces it needs,
* what must remain standalone,
* what should become a service,
* what data contracts are required,
* and where the new corporation should call it.

Do not duplicate working infrastructure merely to make the new
repository look self-contained.

\---

# 15\. Shared Brain / Institutional Memory

The company needs persistent institutional memory.

Obsidian-style Markdown is a useful human-readable representation, but
the architecture must not depend exclusively on Obsidian as the
underlying database.

Separate:

### Structured system state

from:

### Human-readable knowledge

The system should support:

* research notes,
* experiment records,
* strategy records,
* meeting summaries,
* agent memories,
* decisions,
* failed hypotheses,
* lessons learned,
* evidence links,
* relationships between concepts.

The long-term goal is a navigable knowledge graph.

Example:

``` text
Hypothesis H-1842
   ↓
Experiment E-501
   ↓
Result R-501
   ↓
Strategy S-031
   ↓
Validation V-044
   ↓
Paper Run P-018
```

And:

``` text
H-1842
 ├── inspired by → Observation O-91
 ├── challenged by → Critique C-32
 ├── replicated by → E-509
 └── rejected because → Finding F-72
```

\---

# 16\. Organizational Self-Improvement

The company should eventually research itself.

Examples:

* Does 3 technical analysts outperform 2?
* Does adding an adversarial researcher reduce false discoveries?
* Which skills improve research quality?
* Which meeting structures produce useful decisions?
* Which agents produce reproducible research?
* When should research teams expand?
* Which departments create the most valuable discoveries?
* Which agents duplicate each other?

Organizational experiments must be measured.

Do not assume more agents = better performance.

\---

# 17\. Agent Performance

Agents should have measurable performance records.

Possible metrics:

### Researcher

* useful hypotheses
* successful replications
* invalid hypotheses detected
* research quality
* reproducibility

### Analyst

* evidence quality
* information freshness
* prediction calibration
* useful observations

### Critic

* false discoveries caught
* important weaknesses discovered
* review usefulness

### Risk Manager

* risk violations prevented
* false-positive rate
* quality of risk decisions

### Trader

* execution quality
* adherence to approved instructions
* operational accuracy

Do not evaluate agents solely on P\&L.

\---

# 18\. Mission System

The company operates through missions.

A mission should contain:

``` text
mission\_id
objective
scope
priority
owner
participating departments
participating agents
constraints
deadline
research budget
status
progress
outputs
decisions
```

Example:

``` text
MISSION 047

Objective:
Discover robust cross-sectional predictive signals.

Departments:
Market Intelligence
Quant Research
Strategy Lab
Risk

Status:
67%

Hypotheses:
183

Experiments:
241

Survivors:
7

Rejected:
176

Active agents:
27
```

Missions should be visible throughout Mission Control.

\---

# 19\. Mission Control / Station

The visual station is NOT an optional decorative dashboard.

It is the primary human interface to the organization.

The user should be able to operate the entire system without opening:

* terminals,
* source files,
* agent chats,
* raw logs,
* or internal databases.

The station must expose the underlying system through a coherent visual
environment.

\---

# 20\. Visual Design Direction

The UI should use the same general philosophy as the existing AI
Research Civilization station:

### Style

* pixel-art inspired
* industrial research facility
* dark sci-fi
* mechanical infrastructure
* research-laboratory atmosphere
* subtle futuristic elements
* highly readable
* dense but organized
* game-like without becoming childish

Avoid:

* generic SaaS dashboards,
* excessive glassmorphism,
* generic neon cyberpunk,
* overly clean corporate UI,
* excessive gradients,
* visual clutter.

The facility should feel like:

> \*\*an actual autonomous quantitative research corporation operating
> inside a physical research complex.\*\*

\---

# 21\. Station Layout

The station should conceptually contain:

``` text
┌──────────────────────────────────────────────────────────┐
│ COMPANY STATUS / MISSION / MARKET / ALERTS              │
├──────────────────────────────────────────────────────────┤
│                                                          │
│   MARKET INTEL       QUANT RESEARCH       STRATEGY LAB   │
│                                                          │
│   \[agents]           \[experiments]        \[debates]      │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│              CENTRAL RESEARCH / DATA CORE                │
│                                                          │
│       data → research → experiments → results            │
│                                                          │
├───────────────────────┬──────────────────────────────────┤
│ PORTFOLIO / RISK       │ TRADING OPERATIONS              │
│                       │                                  │
│ exposures             │ positions                       │
│ limits                │ orders                          │
│ strategy allocation   │ execution                       │
├───────────────────────┴──────────────────────────────────┤
│ ARCHIVE / KNOWLEDGE / INFRASTRUCTURE / SYSTEM STATUS     │
└──────────────────────────────────────────────────────────┘
```

This is conceptual. The actual UI should be designed after repository
and technology audit.

\---

# 22\. Facility Interaction

Users should be able to click:

### Company

→ company-wide status

### Department

→ department dashboard

### Team

→ team members, tasks, output

### Room

→ room-specific visualization

### Agent

→ agent profile, current task, memory, messages, skills, performance

### Mission

→ mission timeline and progress

### Hypothesis

→ evidence and experiment history

### Experiment

→ exact configuration and result

### Strategy

→ strategy lifecycle and performance

### Portfolio

→ exposures, strategies, risk

### Trade

→ decision chain and execution history

### Alert

→ source, severity, affected components, recommended action

Everything should be drill-downable.

\---

# 23\. Agent Detail View

Clicking an agent should reveal something like:

``` text
AGENT TA-03
Technical Analyst

STATUS
● ACTIVE

CURRENT MISSION
M-047

CURRENT TASK
Evaluate cross-sectional momentum under regime X

SKILLS
Technical Analysis
Regime Analysis
Statistical Research

CURRENT ACTIVITY
Running experiment E-501

RECENT OUTPUT
7 observations
3 hypotheses
2 critiques

PERFORMANCE
Research quality: ...
Replication success: ...
```

The UI should allow the user to inspect what the agent is actually
doing.

\---

# 24\. Research Detail View

Every experiment should be inspectable.

Show:

* hypothesis
* preregistration
* data
* methodology
* parameters
* result
* statistical metrics
* visualizations
* critiques
* replications
* decision
* linked strategies
* provenance

The user should be able to trace:

> "Why does the company believe this strategy exists?"

all the way back to raw evidence.

\---

# 25\. Strategy Dashboard

A strategy page should show:

* current state
* thesis
* latest version
* performance
* drawdown
* turnover
* costs
* exposure
* correlation with other strategies
* validation status
* research evidence
* recent changes
* known weaknesses
* paper-trading status
* risk constraints

Never present a single performance number as proof of quality.

\---

# 26\. Company Timeline

Mission Control should have a chronological company timeline.

Example:

``` text
09:01  Analyst discovered unusual relationship
09:07  Hypothesis H-1842 created
09:14  Researcher preregistered experiment
09:31  Experiment E-501 completed
09:34  Critic challenged result
09:42  Replication requested
10:03  Replication failed
10:07  Hypothesis downgraded
10:15  New research direction proposed
```

This makes the organization feel alive.

\---

# 27\. Observability

Everything important must be observable.

The system needs structured logging and event telemetry.

At minimum track:

* agent state
* task state
* mission state
* experiment state
* model calls
* tool calls
* errors
* latency
* token/cost usage
* research outcomes
* decisions
* execution events
* alerts

But raw logs should remain an internal implementation detail.

Mission Control should turn them into useful human-readable information.

\---

# 28\. Architecture Principles

Prefer clear boundaries:

``` text
UI
 ↓
Application API
 ↓
Orchestration
 ↓
Agent Runtime
 ↓
Department Services
 ↓
Research Engines / Data / Execution
 ↓
Persistence
```

Use event-driven architecture where it provides real value.

Do not introduce microservices simply for appearance.

Start modular and evolve toward distributed components only when
justified.

\---

# 29\. Technology Selection

Do not blindly assume a stack.

First audit the repository and existing environment.

Choose technologies based on:

* reliability,
* maintainability,
* developer speed,
* Python compatibility,
* AI integration,
* real-time UI requirements,
* data volume,
* reproducibility,
* observability,
* and ease of deployment.

Likely areas include:

* Python backend
* agent orchestration layer
* PostgreSQL or equivalent structured database
* time-series/data storage
* object storage for research artifacts
* event/message system
* WebSocket/SSE real-time updates
* React/Next.js frontend
* charting/visualization
* Markdown/knowledge layer

But these are suggestions, not mandates.

\---

# 30\. Development Strategy

Build vertically.

Do NOT create hundreds of empty agents and folders first.

Build the smallest complete organism that can:

``` text
Mission
 ↓
Agent
 ↓
Research task
 ↓
Experiment
 ↓
Result
 ↓
Memory
 ↓
Mission Control
```

Then expand.

Each milestone should produce working functionality.

\---

# 31\. Phased Expansion

Suggested progression:

## Phase 0 --- Repository Audit \& Architecture

Understand the current repository before changing it.

## Phase 1 --- Core Platform

Build:

* configuration
* persistence
* event model
* agent abstraction
* task system
* mission system
* basic API
* observability

## Phase 2 --- First Research Department

Build a small functioning research organization.

Example:

* 1 lead researcher
* 2 researchers
* 1 critic
* 1 statistical validator

## Phase 3 --- Experiment Engine

Integrate:

* backtests
* experiment registry
* provenance
* Monte Carlo
* robustness testing

## Phase 4 --- Knowledge System

Build institutional memory and knowledge graph.

## Phase 5 --- Market Intelligence

Add fundamental/news/sentiment/technical capabilities where data access
is available.

## Phase 6 --- Strategy Laboratory

Add strategy synthesis, debate, replication, and validation.

## Phase 7 --- Portfolio \& Risk

Add independent risk and portfolio layers.

## Phase 8 --- Paper Trading

Connect validated strategies to paper execution.

## Phase 9 --- Mission Control Station

Build the full facility interface and real-time monitoring.

## Phase 10 --- Organizational Self-Research

Let the corporation evaluate its own structure, agents, skills, and
workflows.

## Phase 11 --- Hardening

Security, reliability, failure recovery, auditability, testing,
performance, deployment.

\---

# 32\. Testing

Testing is mandatory.

At minimum:

### Unit tests

For deterministic components.

### Integration tests

For department interactions.

### Agent contract tests

Ensure agents obey role boundaries.

### Research integrity tests

Catch leakage and provenance failures.

### Golden tests

Protect important research outputs from accidental changes.

### Simulation tests

Run complete missions in controlled environments.

### Failure tests

Test:

* agent failure
* API failure
* data outage
* malformed results
* duplicated messages
* stale data
* conflicting decisions
* execution rejection

### End-to-end tests

The complete lifecycle must eventually be testable:

``` text
Mission
→ research
→ experiment
→ debate
→ validation
→ strategy
→ risk
→ paper trade
→ result
→ memory
```

\---

# 33\. Cost Control

AI calls can become the dominant operating cost.

The architecture must support:

* model routing,
* caching,
* task prioritization,
* context minimization,
* structured outputs,
* batch processing,
* deterministic computation outside LLMs,
* experiment deduplication,
* agent budgets,
* mission budgets,
* token accounting.

Do not use an expensive frontier model for deterministic tasks.

Use normal software for:

* calculations,
* statistics,
* database queries,
* data transformations,
* backtests,
* chart generation,
* validation checks.

Use LLMs for:

* interpretation,
* hypothesis generation,
* synthesis,
* critique,
* planning,
* communication,
* qualitative reasoning.

\---

# 34\. Anti-Pattern List

Avoid:

* one giant agent
* hard-coded agent prompts everywhere
* agents directly modifying production strategy code without review
* hidden state
* untraceable research
* silent strategy changes
* deleting failed experiments
* treating LLM confidence as evidence
* letting agents cite unavailable data
* uncontrolled agent loops
* unlimited token spending
* unnecessary microservices
* decorative dashboards with no underlying data
* UI that exposes only fake status
* creating hundreds of agents before the runtime works
* assuming more agents means more intelligence
* assuming backtest performance means future profitability

\---

# 35\. Definition of Success

The project is successful when it can demonstrate that:

1. multiple specialized agents genuinely collaborate,
2. agents have persistent roles and reusable skills,
3. research is reproducible,
4. failed research is preserved,
5. hypotheses can move through a rigorous lifecycle,
6. strategies are versioned and evidence-backed,
7. risk is independent,
8. portfolio construction is separate from signal generation,
9. paper trading can operate autonomously,
10. the company learns from its results,
11. the organization can inspect and improve itself,
12. and a human can operate and understand the whole system through
Mission Control without opening the source code.

The visual station is successful when the user can open it and
understand:

> What is happening?
>
> Why is it happening?
>
> Who is doing it?
>
> What has the company learned?
>
> What is it going to do next?
>
> What strategies exist?
>
> Why does the company believe in them?
>
> What risks exist?
>
> What failed?
>
> What needs attention?

\---

# 36\. First Principle for Claude Code

Before writing substantial code:

**AUDIT FIRST.**

Inspect:

* repository structure
* existing architecture
* existing documentation
* existing dependencies
* current runtime
* existing tests
* existing data infrastructure
* existing `martex-quant` integration points if available
* existing UI
* existing configuration
* existing scripts
* existing agent infrastructure
* existing research infrastructure

Then produce an implementation plan.

Do not overwrite or replace existing systems merely because a cleaner
architecture can be imagined.

Preserve useful work.

Refactor only when justified.

\---

# 37\. Working Style

When implementing:

1. Understand before changing.
2. Make architecture explicit.
3. Prefer small, testable modules.
4. Keep interfaces stable.
5. Write tests alongside features.
6. Record important architectural decisions.
7. Keep the system runnable at every milestone.
8. Never fake functionality merely to make the UI look complete.
9. Never fabricate research results.
10. Never claim a strategy works without evidence.
11. Keep simulation/paper execution clearly separated from live
execution.
12. Document trade-offs.

When something is uncertain:

* investigate,
* test,
* document,
* then decide.

Do not guess silently.

\---

# 38\. The North Star

The final system should feel like:

> \*\*A living quantitative research corporation.\*\*

You should be able to open the Mission Control station and see:

* researchers investigating ideas,
* analysts collecting evidence,
* agents debating,
* experiments running,
* hypotheses being killed,
* strategies evolving,
* risk managers evaluating exposure,
* portfolios being constructed,
* paper trades being executed,
* knowledge accumulating,
* and the organization learning from its own history.

The system should not merely *simulate* a company through chat.

It should actually have the software architecture necessary for the
company to function.

Build the **organization first**.

Build the **intelligence second**.

Build the **strategy third**.

Build the **trading operations fourth**.

Build the **visual station as the window into the organization**, not as
a substitute for the organization.

And throughout the project:

> \*\*Evidence over narrative.\*\*
>
> \*\*Reproducibility over impressive demos.\*\*
>
> \*\*Robustness over backtest optimization.\*\*
>
> \*\*Independent criticism over consensus.\*\*
>
> \*\*A good failed experiment over a bad successful-looking one.\*\*
>
> \*\*A real functioning organization over a collection of prompts.\*\*

