# 05 — Lifecycles: Research, Strategy, Portfolio, Risk, Trading

Date: 2026-09-04
Status: proposal, v2.

How work actually moves through the company, who touches it at each stage, and
what is deterministic versus what is judgement.

---

## 1. The research lifecycle

### 1.1 The full path

| Stage | Who | Deterministic? | Output |
|---|---|---|---|
| **OBSERVE** | Market Intelligence, per desk | mostly — scans, scheduled pulls | `MarketObservation`, desk briefing |
| **QUESTION** | Research Director, Kickoff meeting | judgement | Mission or project objective |
| **HYPOTHESIZE** | Researchers; Brainstorm meeting | judgement | `Hypothesis` (DRAFT) with a stated minimum effect |
| **SCREEN** | Knowledge dept + novelty check | deterministic | Prior art, duplicate detection, `SCREENED` or `SHELVED` |
| **FORECAST** | All participants | judgement, low tier | `Forecast` rows — before anything runs |
| **PREREGISTER** | Registrar | deterministic | `Registration` locked and hashed |
| **DESIGN** | Quant Researcher + Research Engineer | judgement | Experiment spec over registered operations |
| **RUN** | Engines | **fully deterministic** | `Run`, `Result`, `Artifact` |
| **ANALYZE — statistics** | Statistical Researcher via capabilities | **fully deterministic** | Metrics, intervals, deflated Sharpe |
| **ANALYZE — meaning** | Analysts | judgement | `Finding` — interpretation, no fabricated numerals |
| **DERIVE VERDICT** | rule | **deterministic** | Verdict from the interval vs the *registered* criteria |
| **CRITIQUE** | Strategy Critic, Adversarial, Auditors, Skeptic | judgement | `Objection` + discriminating test |
| **RESOLVE** | Engines run the tests | deterministic | Objection upheld or rejected |
| **REVIEW MEETING** | Research Review | judgement | Verdict accepted, contested, or sent back |
| **REPLICATE** | Replication Researcher | judgement + deterministic run | Independent re-test with a declared variation |
| **ROBUSTNESS** | Robustness Researcher | deterministic grids | Parameter, period, universe, cost, regime stress |
| **OUT-OF-SAMPLE** | Custodian | **deterministic, counted** | One sealed-window query, audited |
| **PORTFOLIO TEST** | Correlation + Exposure Analysts | deterministic | Interaction with the existing book |
| **PROMOTE** | Strategy Committee | judgement against registered gates | Strategy version promoted or refused with a reason |
| **PAPER DEPLOY** | Trading Ops under Risk limits | deterministic | Paper account activated |
| **MONITOR** | Position Monitor, Post-Trade Analyst | deterministic | Live-vs-backtest gap, alerts |
| **RETROSPECTIVE** | Everyone who worked on it | judgement | Lessons → memory; org proposals → Board |

### 1.2 The line that must not move

**Agents interpret. Software computes.**

- No metric is produced by a model.
- No verdict is chosen by a model — it is derived from the computed interval
  and the *preregistered* criteria.
- No confidence is asserted by a model — it is computed from evidence.
- A turn or finding containing a numeral that is not in the evidence pack or a
  tool result is rejected by a validator.

This is what makes a company of language models a research organization
instead of a very articulate opinion generator.

### 1.3 Where the graveyard lives

Refuted and inconclusive hypotheses are **kept forever**, with their evidence,
their reasoning, and the reason they died. They are:

- injected into every Brainstorm's evidence pack ("we tried this in March; here
  is what happened"),
- counted in the multiple-testing denominator, so every future claim's bar is
  raised by every trial ever run,
- rendered as a first-class room in Mission Control, not a hidden tab.

A researcher that correctly kills a bad strategy has produced valuable work,
and the metrics record it that way.

---

## 2. Strategy lifecycle

```
IDEA ──▶ CANDIDATE ──▶ RESEARCHING ──▶ PROMISING ──▶ UNDER_REVIEW ──▶ VALIDATED
                            │              │              │               │
                            ▼              ▼              ▼               ▼
                        REJECTED       REJECTED       REJECTED     PAPER_TRADING
                                                                         │
                                     ┌───────────────────────────────────┤
                                     ▼             ▼                     ▼
                                MONITORING ──▶ DEGRADED ──▶ SUSPENDED ──▶ RETIRED
```

| Transition | Requires |
|---|---|
| IDEA → CANDIDATE | A written thesis and a desk |
| CANDIDATE → RESEARCHING | An accepted project and assigned researchers |
| RESEARCHING → PROMISING | ≥1 confirmed finding with computed confidence ≥ SUPPORTED |
| PROMISING → UNDER_REVIEW | All registered gates evaluated; zero open CRITICAL objections |
| UNDER_REVIEW → VALIDATED | Strategy Committee decision, with Risk and Audit present |
| VALIDATED → PAPER_TRADING | Risk assessment with limits; Trading Ops activation |
| PAPER_TRADING → MONITORING | Automatic after the first full period |
| MONITORING → DEGRADED | A **preregistered** degradation rule fires — not judgement |
| DEGRADED → SUSPENDED | Risk decision, or a second degradation trigger |
| any → RETIRED | Board or Head of Strategy decision, with recorded reason |

**Backward transitions are normal** and always carry the triggering
measurement.

### 2.1 Versioning

> A `VALIDATED` version is immutable. A material change creates a new
> `StrategyVersion` at `UNDER_REVIEW` and triggers revalidation.

Enforced by trigger. Material = universe, signal, entry, exit, sizing, cost
model, or any parameter that appeared in a declared cell.

Every result row carries `version_id`, so history cannot be silently restated
by editing a spec.

### 2.2 Re-opening a killed strategy

Requires a **new specification and a stated substantive reason**. A boilerplate
reason fails the check. The rationale is that re-testing killed ideas until one
passes is the single most effective way to manufacture a false discovery, and
the ledger's denominator has to see it.

---

## 3. Promotion gates

Registered **before** evaluation, per strategy, so success criteria cannot be
chosen after seeing results.

| Gate | Criterion | Owner |
|---|---|---|
| **A — Statistical** | Deflated Sharpe ≥ threshold against the **lifetime** trial count, not the family's | Statistical Researcher |
| **B — Benchmark** | Beats the desk's naive benchmark on the same instruments, window and costs | Validation Researcher |
| **C — Independence** | Correlation with every deployed strategy below a registered bound | Correlation Analyst |
| **D — Integrity** | Zero open CRITICAL objections; point-in-time universe; realistic costs and liquidity | Backtest + Data Auditors |
| **E — Replication** | ≥1 surviving independent replication with a declared variation | Replication Researcher |
| **F — Custody** | At most one sealed-window query, and it passed | Custodian |
| **G — Capacity** | Capacity ≥ intended allocation at realistic participation | Capital Allocation Analyst |

Gate B exists because a strategy that loses to buy-and-hold is not a strategy.
Gate C exists because **the best individual strategy is not automatically a
portfolio component** — a strategy can pass every solo test and still add
nothing to a book it correlates with.

Thresholds are per-desk configuration, registered and versioned.

---

## 4. Portfolio lifecycle

```
Approved strategy signals
        ↓
SIGNAL AGGREGATION          Strategy Lab — combine, deconflict, normalise
        ↓
PORTFOLIO CONSTRUCTION      Portfolio Manager — target weights per desk
        ↓
CAPITAL ALLOCATION          Allocation Analyst — capacity and budget per desk
        ↓
INTERACTION ANALYSIS        Correlation + Exposure Analysts
        ↓
RISK ASSESSMENT             Risk — independent, can veto
        ↓
Target book
```

Portfolio-level questions are ordinary research hypotheses with ordinary
specifications, run through the same lifecycle: correlation stability,
concentration, factor overlap, drawdown interaction, liquidity, leverage,
turnover, capacity, regime dependence, cross-desk diversification.

The Portfolio & Risk department reviews the book on a schedule and after any
allocation change, in a **Risk Committee** meeting.

---

## 5. Risk authority

Risk is independent because it is **structurally unbypassable**, not because a
role is told to be firm.

Risk may:

- reject a trade proposal outright,
- shrink requested exposure,
- impose or tighten limits (per strategy, desk, factor, or company),
- suspend a strategy,
- halt all execution on a desk or company-wide,
- flag abnormal conditions and demand review,
- require a Risk Committee before any deployment.

Every risk decision is recorded **including the ones that change nothing**, so
"Risk allowed it" and "Risk was never consulted" are distinguishable rows.

### The three numbers

Persisted on every proposal, always:

```
desired_exposure     what the strategy asked for
allowed_exposure     what Risk permitted
final_target         what portfolio construction settled on
```

### Kill switches

Inherited in spirit from martex-quant's guard: preregistered drawdown and floor
tripwires that flatten and latch. **A latched kill is never cleared by code** —
clearing it is a deliberate human act after understanding what died.

---

## 6. Trading operations

```
Approved target book
        ↓
MARKET SETUP ANALYSIS      Are current conditions suitable? Desk-specific.
        ↓
TRADE PLANNING             Target exposure → executable orders
        ↓
APPROVAL CHECK             Approval chain intact? Limits? Halts? Kill latch?
        ↓
EXECUTION                  BrokerAdapter.submit — paper only
        ↓
POSITION MONITORING        Live positions, drawdown, divergence
        ↓
POST-TRADE ANALYSIS        Slippage, cost attribution, backtest-vs-live gap
        ↓
FEEDBACK                   The gap becomes research input and a scored forecast
```

### The execution boundary

| Adapter | Status |
|---|---|
| `BacktestBroker` | implemented — the engine's simulated fills |
| `SimulationBroker` | implemented — scenario replay |
| `PaperBroker` | implemented — forward testing on simulated capital |
| `LiveBroker` | **not written, not registered, not reachable** |

`Portfolio.mode` has no `LIVE` member. Aurelis creates no path to
martex-quant's MT5 adapter, and a test asserts no module imports it. Enabling
real-money trading is a separate, separately-reviewed project — not a flag.

### The backtest-live gap

The most valuable measurement the company makes, because it is the only one
where reality gets a vote. For every paper-traded strategy:

```
gap = realised_metric − backtest_expectation
```

tracked per strategy, per desk, per cost component. Every deployment carries a
**scored forecast** of its own gap, so the company learns how wrong its
backtests tend to be — which is a company-level competence, not a strategy
property.

---

## 7. Alerts and escalation

| Alert | Raised by | Goes to |
|---|---|---|
| Drawdown breach | Position Monitor | Risk, Head of Trading → Risk Committee |
| Kill latch tripped | Risk engine | Everyone, immediately |
| Data staleness / gap | Data Systems Engineer | Infrastructure, affected desks |
| Chain verification failure | Ledger Officer | Chief Auditor, Board |
| Budget exhaustion | Budget Officer | Mission owner, Executive |
| Live-vs-backtest divergence | Post-Trade Analyst | Strategy Lab, Risk |
| Calibration collapse | Forecast Scorer | Org Development Lead |
| Audit finding, severity CRITICAL | any Auditor | Named agent + Board |
| Unresolved deadlock | Chair | Next meeting up the chain |

Escalation always creates a `Task` for the receiver, and above a threshold
calls a meeting. Nothing escalates into a void.

---

## 8. Scheduled operations

The company has a working day, driven by the scheduler rather than by an agent
deciding to act.

| Cadence | Operation |
|---|---|
| Continuous | Data ingestion and validation per active desk |
| Hourly | Position monitoring, alert evaluation, queue health |
| Daily | Desk briefings; paper-trading cycle; freshness checks; budget report |
| Daily | Team standups (cheap, one round) |
| Weekly | Board meeting; portfolio review; calibration report; org metrics |
| Weekly | Audit sampling — a random draw of recent research is re-checked |
| Monthly | All-Hands; knowledge-graph consolidation; playbook regression on scenarios |
| On event | Research Reviews, Debates, Committees, Incident Reviews |
| Per mission | Kickoff and Retrospective — mandatory |

Idle costs nothing. A department with no work makes no model calls.
