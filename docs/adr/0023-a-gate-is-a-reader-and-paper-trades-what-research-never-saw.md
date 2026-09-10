# ADR-0023 — A gate is a reader, and paper trades what research never saw

Status: accepted · 2026-09-10

## Context

M20's mandate reported `risk_cleared` and `paper_gap_measured` as unmet, with a
note that they were *satisfiable*: `PaperCycle` was built and tested at M9 and
no command drove it. That framing was wrong, and building the command is what
showed it.

Nothing was missing a switch. A version reaches a paper book only through
`Strategies.promote`, which refuses unless **every** promotion gate was
evaluated and every one passed. The seven gates had criteria since M8 and their
observables had never been fetched from anywhere — every test that promoted a
version supplied the numbers by hand. So the question an operator actually
needed answered was not "how do we start paper trading?" but **"what is
stopping us, and can the company even tell?"**

## Decision

### A gate is a reader over the company's own record

`aurelis/trading/readiness.py` fetches seven observables:

| gate | observable | read from |
| --- | --- | --- |
| A | `deflated_sharpe` | the attempt's Sharpe, the registration's bar count, the family's trial count, through martex-quant |
| B | `excess_sharpe_over_benchmark` | the attempt's Sharpe minus its `always_long` baseline |
| C | `max_correlation_with_deployed` | the book's live allocations |
| D | `open_critical_objections` | objections against the version's chain |
| E | `surviving_replications` | replications of its registration that held |
| F | `sealed_queries_used` | results on the sealed split |
| G | `capacity_over_intended_allocation` | a snapshot's own median bar volume |

Every reader either finds its number or returns **silence with a sentence
saying what is absent**. Silence is not zero. That distinction is the whole
design, and it runs in exactly the direction that matters: a default of zero
promotes strategies.

### Two silences are holes in the criteria, not in the data

Writing the readers found both, and neither was patched away:

**Gate F counts sealed queries and passes at zero.** Its own note says "and it
must have passed", but `sealed_queries_used lte 1` is most easily satisfied by
never asking. A version that never touched the held-out data avoided custody
rather than clearing it, so the reader returns silence instead of the zero the
criterion would have accepted. There is no sealed-query mechanism in this
repository yet — a scope, a CHECK, and nothing that releases one — and gate F
now says so out loud instead of passing.

**Gate D counts open critical objections and passes at zero.** A design nobody
read has none. The reader returns silence when no objection was ever raised
against the version's chain at all, and the count once a critic has looked.

### Paper trades bars the research window never read

A walk over the window the backtest ran on is not a forward test. It is the
backtest again, paying different fees, and calling its difference a
backtest-live gap would be the fake this project exists not to build.

So `SnapshotSource` gained `upto`, `paper.held_out` reserves 30% of a snapshot,
and `strategy author --snapshot` measures on the early window. The walk starts
where the research stopped and `walk()` refuses when nothing is left. The
fraction is fixed rather than an option: a company that chose its out-of-sample
size after seeing the result would be choosing its hold-out, which is the
hindsight-universe defect one layer up.

Three further guards make that real rather than conventional:

- **The rule that trades is the rule that was measured.** `design_of` rebuilds
  the design from the attempt and checks it against the digest the attempt
  recorded, then renders it through the same `render` and evaluates it through
  the same `LocalEngine.weights` the backtest used. A driver with its own copy
  of the signal would measure the distance between two implementations.
- **The claim and the book must be on the same data.** A deployment whose
  registration locked a different source is refused: a gap across two datasets
  measures the distance between the datasets.
- **The curve is derived, not accumulated.** `sleeve_curve` rebuilds
  mark-to-market equity out of the fills after the walk, so the number the gap
  is measured from is a consequence of what the database says happened.

### Risk sets the ceiling before the first intent exists

`deploy` writes an exposure limit at the sleeve. An assessment against no limit
allows whatever was asked for, which is Risk agreeing with the strategy rather
than bounding it — and `risk_cleared` would have been satisfied by that.

## Consequences

- **The company can now say exactly what stops it, and it is not machinery.**
  On a full run: gate A fails (deflated Sharpe 0.0 against a bar of 0.95), gate
  B fails (the design loses to buy-and-hold), gate E fails (no replication has
  held), and gates D and F are silent. Gate C passes on an empty book and says
  so; **gate G passes on real volume** — a median BTC-USD hour traded about
  13.1m, one per cent of which is five times the 25,000 the sleeve intended.

- **`risk_cleared` and `paper_gap_measured` are still unmet, and that is the
  correct answer.** Both are downstream of promotion. A command that produced a
  risk assessment for a version the gates rejected would be manufacturing the
  evidence the mandate asks for, which is precisely the move the mandate exists
  to catch. What M22 changes is that the operator can now see *why*, computed,
  gate by gate, instead of reading "0 risk assessments".

- **The report was lying about its data.** `caveat_for` knew whether a model or
  the stand-in had answered and hard-coded "the data is a fixture rather than a
  market" — so the first authoring run against 3,000 hours of BTC-USD printed a
  caveat that was false. Both halves are conditional now. This is the same
  defect as M18's, in the same sentence, found the same way: by running the
  thing.

- **The driver was running a different strategy.** The first walk placed an
  order on all 275 bars where the backtest had traded 52 times in 2,100. The
  intent compared the target notional against the position's *market value*,
  which drifts with the price every bar — so a rule holding one position for a
  week rebalanced seven times. The engine holds a target *weight* and charges
  only when the weight changes; a driver that rebalanced to constant notional
  would report the difference between two strategies as a backtest-live gap.
  An intent now fires when the rule changes its mind, with entry and exit still
  triggered by the book.

- **`cost_drag` was comparing two different quantities.** The paper figure
  counted only the explicit broker fee, while the engine's charges its whole
  declared cost model — fees, spread and slippage — so paper read as half as
  expensive (0.042 against 0.099). Charging the slippage too puts them within
  0.004 of each other, which turns an artefact into a finding: on this window
  the desk's cost model was about right.

- **A gap measured forward is not an execution cost.** The corrected walk
  reports every metric holding — total return +0.155, Sharpe +0.045, drawdown
  −0.056 — and none of that is the strategy being good. The held-out window is
  a different stretch of market from the one the backtest read, so the number
  mixes how wrong the claim was with how different the two periods were.
  `aurelis trading paper` says so under the table, and it is the reason
  `PostTrade.company_gap` aggregates across deployments: one run cannot
  separate them.

- **Deploying twice walked the strategy backwards.** The second call tried to
  move a `paper_trading` strategy to `candidate`; the state machine refused, as
  it should, with a traceback at an operator who typed a command twice. A live
  allocation is now answered before anything is written, and `already` is a
  separate field from `deployed` so a re-run cannot read as a decision.

- **An approval is a ceiling and the size now rounds down.** `PaperCycle` sized
  orders with `quantize`'s default half-even rule, which rounds *up* about half
  the time; a notional a hundred-millionth over the approval is refused
  outright by `Execution.submit` and by the CHECK behind it. Never hit before
  because no caller had run the cycle across hundreds of bars.

- **A run may be handed its engine.** `research.execute` takes an optional
  engine so a registration can be measured against a recorded snapshot. It
  widens *which bars*, never *which numbers* — the artifact still carries the
  source's name and the fingerprint of what it read, and an engine whose name
  disagrees with the locked specification is refused.

- **Three engine methods became public.** `weights`, `sharpe_with_interval` and
  `max_drawdown`. Paper trading has to ask the same questions the backtest
  asked, and the alternative to sharing the implementation is two of them.

- **Nothing in the test suite touches the network.** The snapshot is ingested
  from a recorded payload, as at M21.
