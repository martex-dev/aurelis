# 00 — Repository & Ecosystem Audit

Date: 2026-09-04
Status: complete. No code changed.

---

> **Note (v2).** This audit is the factual record of what exists on this
> machine. Its *conclusions* were superseded by
> [ADR-0001](adr/0001-aurelis-is-its-own-system.md): Aurelis is a **new system
> with its own architecture**, and both systems below are dependencies with
> bounded roles — martex-quant as a tool in the toolbox, nullius as platform
> patterns plus one service department. Section 7 has been rewritten to match.
> Sections 1-6 are left as written, because the facts have not changed.

## 1. What exists

`C:\Users\PC Games\Desktop\Aurelis` contains exactly one file: `CLAUDE.md`.
But the machine is not empty.

Two mature systems already exist here, and between them they contain a great
deal that Aurelis can use — not as sketches, but as tested, CI-green,
documented software with committed research records behind it.

| System | Location | Size | Tests | What it is |
|---|---|---|---|---|
| **nullius** | `Desktop/new project` | 27,906 LOC / 102 files | 547 | An artificial **research institution**: roles, task queue, budgets, preregistration, custody, adversarial challenge, replication, evidence-typed memory, hash-chained ledger, and a facility-metaphor **station** UI |
| **martex-quant** | `Desktop/Trading Bot` | 14,058 LOC / 108 files | 528 | A **quantitative research engine**: validated data lake, event-driven backtester, walk-forward, deflated Sharpe, Monte Carlo prop simulation, paper trading, risk guard, trial ledger of 174 registered trials |

Plus nine small, focused, separately-published research-integrity tools under
`Desktop/projects/` (`leakguard`, `timeleak`, `purged-cv`, `calibrate`,
`cv-visualizer`, `factor-exposure`, `vol-surface`, `roll-yield`,
`implied-move`).

Neither is a corporation, and neither is a template for one. What they are is
a well-built crypto research engine, a rigorous single-pipeline research
instrument, and nine sharp little tools — roughly one desk's worth of
engineering, five integrity mechanisms worth reimplementing, and 174 trials of
institutional memory worth importing.

The rest of this document is what each part is actually worth to Aurelis.

---

## 2. nullius — the institution machinery

### What it already does

`nullius` was built to answer one falsifiable question: *does institutional
structure — preregistration, adversarial challenge, independent replication,
evidence-typed memory — improve the accuracy and calibration of autonomous
empirical research?*

That is `CLAUDE.md` §16 ("organizational self-improvement"), already built and
already producing negative results.

| Module | LOC | Maps to `CLAUDE.md` |
|---|---|---|
| `db/` (tables, enums, triggers, rows) | 1,644 | §4 domain model, §9 research integrity |
| `runtime/` (worker, queue, budget, guard, contracts) | 1,117 | §3 agent model, §33 cost control |
| `roles/` (contracts, views, schemas) | 491 | §4 roles, §5 skills, §3 permissions |
| `ledger/` (hash chain, rebuild) | 513 | §15 institutional memory, §27 observability |
| `knowledge/` (memory, genealogy, novelty, followups) | 774 | §15 knowledge graph |
| `economy/` | 2,891 | §33 cost control, §18 mission budgets |
| `llm/` (providers, cache, pricing, retry) | 950 | §33 model routing |
| `custody/` | 362 | §9 leakage defence |
| `adversarial/` | 912 | §7 debate, §9 integrity |
| `station/` | 5,553 | §19–26 Mission Control |
| `benchmark/` + `bank/` | 3,924 | §16 organizational self-research |

### The five design decisions worth inheriting wholesale

These are stated in nullius's own `docs/00-README.md`, and each is load-bearing:

1. **Norms are invariants, not instructions.** Preregistration is a content
   hash written before dispatch and checked by a database trigger
   (`db/triggers.py: run_requires_prior_registration`). An agent cannot HARK
   because a constraint refuses the row — not because a system prompt asked
   nicely. There are four such triggers: `append_only`,
   `run_requires_prior_registration`, `registration_immutable_once_locked`,
   `forecast_before_execution`.

2. **No number passes through a language model.** Every statistic is computed
   by library code; reports are template-rendered from the database, with LLM
   prose confined to slots that reject numerals (`roles/views.py: no_numerals`).
   This deletes fabrication as a category rather than mitigating it.

3. **Agents do not converse.** Every action is
   `typed state view → validated artifact → append-only event`. A blackboard
   with a ledger, not a chat room. Replay, provenance, audit and cost control
   all fall out of that one choice.

4. **Refutation is a success.** `REFUTED` and `INCONCLUSIVE` are terminal
   states reported with the same prominence as `INSTITUTIONAL`. `Verdict` even
   splits `INCONCLUSIVE` (a finding about the world — a real effect, smaller
   than claimed) from `UNDERPOWERED` (a statement about the design — an
   abstention). They added that split after discovering the collapse had
   inflated every arm's accuracy by four to nine items out of sixty.

5. **Confidence is computed, never asserted.** `ClaimConfidence` is a function
   of replication count, effect size over interval width, open critical
   objections, preregistration status, and holdout queries consumed.

### The information-asymmetry mechanism

This is the piece `CLAUDE.md` §3 gestures at ("permissions = what it is allowed
to do") and nullius has actually implemented. A role's **view** is the entire
world it sees:

```python
@register_view("theorist.question")
def _theorist_question(repo, task) -> dict[str, Any]:
    """The research question, the metric, and the claimed effect. Nothing else."""
```

Registering a view is the *only* way to widen what a role can look at. "What
did the Skeptic know?" is answered by reading a registry, not by tracing call
sites. The Designer is never handed the generator parameters, because an agent
told which features moved would not need to run an experiment.

This is a far stronger permission model than role-based access control, and it
is exactly what a research organization needs.

### Builder-as-compiler (ADR-0004)

Agents never write free-form code. The Designer emits a *specification* that
names operations from a closed registry (`build/ops.py`: generators,
transforms, estimators, metrics). The Builder compiles that spec into a code
bundle. The space of expressible experiments is small, human-written and
unit-tested — "rather than whatever a model improvised this time."

Aurelis adopts the *pattern* — agents compose specifications from registered
operations; engines compile and run them — in its own `engines/` layer. See
`docs/01-architecture.md` §7.

### The station

`nullius station build --out site/station.html` draws the institution as a
cutaway industrial facility: fifteen rooms laid out from `db/enums.py` rather
than beside it, so every role is stationed somewhere and every state of the
research machine is owned by exactly one room. Two rooms have no corridor into
them — the Vault (custodian holds the evaluation split in its own process) and
the Oracle (ground truth the institution may never read).

Disciplines worth keeping, all enforced by tests:

- **`Figure` has no constructor that omits `source`** — a number cannot reach
  the page without naming the file or table it was read out of.
- **Every label is measured** and a test asserts no two text boxes intersect.
- **The station draws the record, not the design** (ADR-0008) — every exit from
  the pipeline is drawn the same width as the entrance, and every one currently
  reads zero, "which is a fact about the code and not about the drawing."
- **No binary assets** — every wall, lamp, console and figure is vector shapes.
  Single file, readable diff.
- **Nothing draws agents conversing**, because the architecture has no
  conversation. "Depicting a meeting would make the picture disagree with the
  system it is a picture of."

That last point is a direct, considered rejection of `CLAUDE.md` §7. It is
addressed in `docs/01-architecture.md` §6.

### The gap

The station is a **static single-file build** (1.9 MB of generated HTML) from
committed artifacts. Aurelis needs a *live* station. That is the main piece of
station work to do, and the generator-from-record discipline must survive it.

---

## 3. martex-quant — the laboratory

### What it already does

Published to PyPI as `martex-quant` 1.0.1, MIT, Python 3.12+, strict mypy,
ruff-clean, 528 tests, CI green, dashboard updating daily.

```
data/             ccxt collectors, validation that reports and never silently repairs,
                  Parquet lake hive-partitioned by symbol/interval/year, atomic upserts
features/         cross-section, intraday, panel, universe, cross-venue, diagnostics
strategies/       pure functions: History -> target exposure in [-1, +1]
backtesting/      event-driven engine, multi-asset engine, walk-forward, metrics
stats/            deflated Sharpe, bootstrap, multiple-testing correction, cointegration
risk_management/  sizing policy, drawdown tracking, kill switch, prop-firm simulation
execution/        simulated fills with fee + spread + slippage
live/             decision core shared by paper and live, guard with KILLED latch
research/         hypothesis ledger, research graph, rules assistant, robustness
dashboard/        stdlib-only local operations view on 127.0.0.1
```

### The interfaces that matter for integration

Four small, stable, well-named contracts. These are the seams Aurelis plugs into.

```python
class Strategy(ABC):
    def on_bar(self, history: History) -> float:      # target exposure [-1, +1]

class MultiAssetStrategy(ABC):
    def target_weights(self, h: dict[str, History]) -> dict[str, float]

class RiskPolicy(ABC):
    def adjust(self, target, equity, initial_equity, ts) -> float   # a gate, not a suggestion

def run_backtest(df, symbol, strategy, config, risk_policy, warmup_bars) -> BacktestResult
def run_multi_backtest(frames, strategy, config, warmup_bars) -> MultiResult
```

The engine's ordering guarantee is what makes it trustworthy:

> Per bar t: broker fills orders submitted at t−1 at bar t's **open**; history
> advances; strategy sees history only; risk adjusts; portfolio turns an
> exposure change into an order for t+1.

Signal on the close, execution on the next open. **Look-ahead is structurally
impossible**, not merely avoided. That property is worth more than any strategy
in the repository.

Note also that `RiskPolicy.adjust` is documented as "a gate, not a suggestion:
the engine calls it on every bar and uses only its return value." `CLAUDE.md`
§12's independent risk authority already exists at the engine level.

### The research ledger

`research/ledger/` is a smaller, hand-rolled cousin of nullius's `db/`: six
record types (`Trial`, `Family`, `Replication`, `StressTest`,
`EvidenceDescriptor`, `Ledger`) over an append-only TOML corpus, with a
*disposable* SQLite index. Direction of authority: **documents → records →
index, never back.**

Two ideas here that nullius does *not* have and Aurelis should absorb:

- **`Family.declared_cells` is what the family DECLARED, not what it ran.** A
  grid of 20 features × 10 horizons costs 200 even if 50 cells executed. That
  closes the "declare big, run small" loophole in multiple-testing accounting.
- **`Trial.dsr` / `dsr_n_trials` store what was ACTUALLY published and the
  trial count it was actually deflated against.** Nothing is recomputed. That
  is the difference between an audit trail and a re-derivation.

Also worth stealing: `EvidenceDescriptor.weakest`, which reports research
volume, independent families, independent periods and replication counts, and
summarises by the *weakest* dimension — "5,000 trials over one period with no
replication is one observation examined exhaustively."

### `research/assistant.py` — rules as code

> "**It can only object. It never approves.** There is deliberately no
> `approved` flag and no `passed` boolean anywhere here — a checker that
> returns APPROVED invites being read as authorization."

This is the honest form of a gate, and it is the right model for every
automated check in Aurelis.

### `research/graph.py` — the research graph

Answers exactly three questions and refuses to answer more: what does this
depend on; what breaks if it is wrong; is this meta-finding's support actually
independent. `independent_support` discounts pairs joined by a
`CORRELATED_WITH` edge above 0.7 **and reports what it discounted** rather than
silently shrinking a number. It assigns no confidence scores, because "a graph
that scores its own nodes invites the reader to trust the score instead of the
sources."

This is `CLAUDE.md` §15's knowledge graph, already built and already opinionated.

---

## 4. What the research actually found — and why it matters to the design

This is the most important section in the audit, and it is uncomfortable.

**174 registered trials. 173 run. Two strategies ever cleared the bar. One of
them has since been killed by the project's own correction, and the survivors
are losing money in paper trading.**

From `docs/hypotheses/71-point-in-time-universe.md` (2026-08-28):

> **Gate A fails and Gate B fails.** On a point-in-time universe the deployed
> spec keeps **58% of its Sharpe** (1.47 → **0.86**) and **49% of its CAGR**
> (+42.91% → +21.06%) … with **zero parameters changed**.
> **The hindsight universe was doing roughly 40% of the work.**

`config/universe.json` had fixed its 40 symbols by "top 40 by 24h quote volume,
**2026-07-12**" — the *end* of the sample. Only 8 of the 40 existed for the
whole 2018–2026 backtest. Classic survivorship bias, found by the project's own
machinery, after the result was published. DSR fell from 0.990 to 0.2759, and
rotation-stop came off the evaluation path.

From `PROJECT_STATE.md` (paper accounts, all started at $5,000, refreshed
2026-08-26):

| Account | Equity | Since start | Max DD on record |
|---|---|---|---|
| vol-target | $5,248.91 | +4.98% | −0.87% |
| rotation | $4,124.16 | **−17.52%** | −20.67% |
| rotation-stop | $4,671.38 | **−6.57%** | −15.56% |
| crash-bounce | $5,000.00 | 0.00% | — |

And the market-structure finding: crypto's intraday reversion is real but
**smaller than retail execution costs**, confirmed four independent ways.

### What this means for Aurelis

Three things, and they should shape the architecture rather than sit in a
footnote:

1. **The honest prior is that no durable edge exists at this scale.** 174
   trials, one survivor after correction, negative paper performance. Aurelis
   must be architected so that "we looked hard and found nothing" is a
   first-class, well-supported, *reportable* outcome — not a failure state.
   `CLAUDE.md` §1.5 says this aspirationally; the evidence makes it the base
   case.

2. **The most valuable thing the existing corpus produced was H71 — a
   correction to the instrument, not a discovery about markets.** Aurelis's
   highest-value early missions are almost certainly of that kind: auditing the
   174-trial corpus for the biases H71 exposed. That is a real, bounded mission
   with partially known answers, which makes it an unusually good first test of
   whether the institution works.

3. **nullius's own self-research already returned a negative result.** Its
   greedy expected-information-gain allocator showed *no measurable advantage*
   over a random allocator, and an earlier version of that claim was retracted
   by the project's own reproducibility fix. So the prior on "more
   organizational structure produces better research" is also weak. Aurelis
   must be able to report that about itself.

---

## 5. The reusable skill library

`Desktop/projects/` is, without anyone having planned it that way, a
research-integrity skill library:

| Project | Capability | Aurelis skill |
|---|---|---|
| `timeleak` | Static linter for data leakage in time-series ML code | `integrity.static_leak_scan` |
| `leakguard` | Runtime detection of preprocessing leakage at `fit()` | `integrity.runtime_leak_guard` |
| `purged-cv` | Purged k-fold with embargo | `research.purged_cv` |
| `cv-visualizer` | Renders CV leakage as a picture | `station.cv_figure` |
| `calibrate` | Reliability diagrams, ECE/MCE/Brier, Platt, isotonic | `research.calibration` |
| `factor-exposure` | Fama-French loadings with honest trust accounting | `portfolio.factor_attribution` |
| `vol-surface` | IV surface, computed rather than taken from the feed | `intel.vol_surface` |
| `roll-yield` | Roll cost inside commodity ETFs | `intel.roll_yield` |
| `implied-move` | Options-implied move before earnings | `intel.implied_move` |

These should be **wrapped as deterministic skills**, not copied in. `timeleak`
and `leakguard` in particular belong in Aurelis's integrity gate: they
mechanically detect the exact family of failure that H71 exposed.

---

## 6. Problems and gaps

Honest list of what does **not** exist, or exists in a form that will not carry
Aurelis.

### 6.1 There is no oracle in markets — and this is the hardest problem

nullius's central epistemic device is **ground truth**: an oracle that runs the
comparison at a scale no experiment is allowed, over data generated from
structural causal models with *planted* effects. That is what makes "did the
institution reach the right conclusion?" a measurable question rather than an
LLM grading an LLM.

**Markets have no oracle.** There is no `bank/truth.lock.json` for whether
cross-sectional momentum has an edge. Ported naively, Aurelis loses the one
mechanism that made nullius falsifiable, and §16 (organizational
self-research) collapses into the circularity nullius's own critique document
calls "a mirror."

This needs a real answer. Proposed in `docs/01-architecture.md` §8.

### 6.2 The two systems have two incompatible ledgers

nullius: SQLAlchemy, SQLite/Postgres, hash-chained events, append-only
triggers. martex-quant: append-only TOML documents with a disposable SQLite
index. Both are good; neither should simply absorb the other. Resolution in
`docs/adr/0003-two-ledgers-one-record.md`.

### 6.3 The station is static

Built from committed artifacts, offline, single file. Aurelis needs live state,
drill-down navigation, and real-time updates — without losing "every figure
names its source."

### 6.4 martex-quant is workspace-coupled

`workspace.py` `chdir`s into a workspace because "almost every path in this
project is resolved relative to the working directory." Fine for a CLI, hostile
to a long-running service. Aurelis must never `chdir`. Resolution: run
martex-quant work in subprocesses with an explicit workspace — which the
sandbox model wants anyway.

### 6.5 Nothing does market intelligence

No news, sentiment, fundamentals, or alternative data anywhere. `CLAUDE.md` §2
lists six market-intelligence departments. This is genuinely greenfield, it is
the most data-access-constrained part of the vision, and it should be
**postponed**. See the roadmap.

### 6.6 No portfolio-construction layer

martex-quant has `portfolio/portfolio.py`, but it is a single-symbol position
accountant, not a portfolio constructor. `CLAUDE.md` §11's
`signals → aggregation → construction → risk → approval → execution` pipeline
does not exist. The multi-asset engine's weight contract is the seam it should
grow from.

### 6.7 No agent-side observability across the two systems

nullius records LLM calls, costs, events and task outcomes. martex-quant
records equity, fills, trials. Nothing joins them. "What did this claim cost to
produce?" is currently unanswerable end to end.

### 6.8 Live trading

Correctly absent. `live/mt5_broker.py` exists and is unreachable from the CLI;
`live/guard.py`'s `KILLED` latch is never cleared by code. Aurelis must
preserve these gates exactly as they are and add nothing that weakens them.

---

## 7. What to preserve, adapt, and leave alone

**Decision taken (ADR-0001): Aurelis is a new repository with its own
architecture. Both systems below are dependencies with bounded roles.**

### martex-quant — a tool in the toolbox

Reached only through `engines/martex/`, in a subprocess with an explicit
workspace. It helps researchers with part of their work.

| Component | Disposition |
|---|---|
| `backtesting/`, `stats/`, `features/`, `execution/` | **Call it, do not fork it.** Becomes the CRYPTO desk's research engine and a shared statistics library. |
| `data/` (lake, validation, bitemporal series) | **Call it.** The CRYPTO desk's data source. |
| `strategies/` | **Seed vocabulary.** Parameterised operations the engine exposes. |
| `research/ledger/` | **Import once (M6).** 174 trials of real institutional memory, preserved as published, never recomputed. |
| `research/graph.py`, `research/assistant.py` | **Absorb the ideas.** Correlation-discounted independence, and objection-only checking that never approves. |
| `meme/` | **Call it.** The MEMECOIN desk's data source. |
| `risk_management/prop_sim.py` | **Call it.** A capability for ruin and prop-rule analysis. |
| `live/guard.py`, `live/mt5_broker.py` | **Leave alone. Do not reach.** A test asserts no Aurelis module imports them. |
| `dashboard/`, `research/tesla/` | **Out of scope.** Mission Control supersedes the first; the second is a finished study. |

What martex-quant does **not** do in Aurelis: generate hypotheses, decide
anything, talk, or appear to any agent except as tool calls.

### nullius — patterns, plus one service department

| Contribution | Disposition |
|---|---|
| Hash-chained append-only ledger | **Pattern.** Reimplemented in Aurelis `platform/`. |
| Preregistration-before-run triggers | **Pattern.** Reimplemented; the single most valuable idea in either system. |
| Evidence typing and the assertion ladder | **Pattern.** Reimplemented in `research/`. |
| Hierarchical money budgets, refused at dispatch | **Pattern.** Reimplemented in `platform/budget`. |
| Forecast scoring and calibration | **Pattern.** Reimplemented; the backbone of agent performance. |
| Custody: sealed data behind a process boundary | **Pattern + department.** Becomes the Vault. |
| The 11 roles | **One service department.** Institutional Governance — serves the other nine, has no authority over research direction, replaces nobody. |
| Station layout discipline | **Pattern.** Rooms derived from registries, `Figure` cannot omit its source, labels measured and non-overlapping, vector only. |
| `bank/`, `benchmark/` | **Pattern.** Informs Aurelis's synthetic training-scenario engine (ADR-0005). |

### The small projects — desk capabilities

| Project | Becomes |
|---|---|
| `vol-surface`, `implied-move` | OPTIONS desk engine capabilities |
| `roll-yield` | FUTURES and COMMODITIES desk capabilities |
| `factor-exposure` | EQUITIES desk + portfolio factor attribution |
| `timeleak`, `leakguard`, `purged-cv`, `cv-visualizer` | `integrity.*` capabilities, used on every desk |
| `calibrate` | `stats.calibration`, used for agent calibration too |

---

## 8. Assessment

The two existing systems are worth a great deal as **components**, and nothing
as a template for the company. martex-quant is a well-built crypto research
engine with a validated data pipeline and an honest statistics library — one
desk's worth of tooling. nullius is a rigorous single-pipeline research
instrument whose integrity patterns are the best available answer to "how do
you stop an LLM from fooling itself," and whose eleven officers make a good
service department.

Neither is a corporation. Aurelis is the corporation, and it is built here.

What the audit contributes to that build, concretely: a working crypto engine
and data lake on day one, 174 trials of institutional memory to import, five
integrity mechanisms worth reimplementing, nine small tools that become desk
capabilities, and one very good demonstration target — the survivorship
correction the existing corpus found by hand, which Aurelis should find by
itself.
