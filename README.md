# Aurelis

**An autonomous quantitative research corporation.**

Ten departments. Seven market desks. Seventy-six role charters. Agents that
observe, hypothesize, experiment, argue in meetings, decide, build strategies,
manage risk, trade on paper, remember everything — and expand the organization
themselves as the evidence justifies it.

[![CI](https://github.com/martex-dev/aurelis/actions/workflows/ci.yml/badge.svg)](https://github.com/martex-dev/aurelis/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Status: **M40 — paper fills at the price the wake can see.** A paper order placed an hour after a trigger no longer fills at the trigger's close: it fills at the newest close the wake could see, the slippage is on the record, and a firing the wake cannot yet see a price for is refused. Before it, M39: evidence is counted by independent episode.** The first live candidate scheme cleared the bar on twenty-six predictions from one afternoon across thirty correlated instruments; predictions whose horizons overlap are now one episode, a mechanism needs ten of them as well as twenty predictions and must beat the drift by both, and a paper position opened while it qualified closes at its horizon whatever the record says since. Before it, M38: a mechanism may fire on the conjunction it was shown.** The discovery form carries `FIRES_ON: trigger | conjunction`; on `conjunction` a prediction seals only when the second event follows the trigger inside the window, at that instant, so the mechanism is tested on the pattern the agent actually reasoned about. Before it, M37: the facility in pixels.** The station is the brief's
pixel-art research complex under one rule: a pixel carries identity (every
agent's deterministic avatar), measured state (a room's LED blinks and its
sprites move only when it is working; a gathering mechanism's bar is
`scored / 20` with the numbers beside it), or nothing. Before it, M36:
Mission Control shows the hunt.** Every mechanism has a page: the causal
statement, what its author was shown with the in-sample figures labelled as
such, the record against the unconditional base rate, every prediction with
its outcome, the paper trades, and the other agents who were shown the same
trigger and declined, with their reasons. M35: the leverage the agents keep
citing enters the stream.** Both live
mechanisms are stories about liquidation cascades; the company held no
funding rate and no open interest. Under its own grant the service now reads
each instrument's perpetual every wake, records funding and open interest as
events on the spot instrument, derives extreme funding and open-interest
surges with their thresholds in the event, and a mechanism can fire on them
and seal against the spot close. M34: a mechanism is
tested across the universe, not on one chart.** A grant can be drawn from the
venue's own liquidity ranking: the top thirty USD-quoted instruments by
dollar notional, pegged ones set aside by their measured range, the rule and
the ranking frozen on the record with the list. A mechanism seals a
prediction wherever its trigger fires, so the live ones gather evidence
across thirty instruments. M33: the miner shows its evidence, and
the company stated its first mechanism.** Shown that fifteen of sixteen range
breaks on live BTC were followed by a rise — beside the coin-toss figure for
any bar — a real Validation agent stated *breakout stop-cascade momentum
continuation*, with who is on the other side and how fast it decays; three
other agents still declined, and the record says so. It predicts every future
break, sealed before the outcome, and must beat the drift out of sample. M32:
the book and the tape enter the event stream.** Order-book
depth and taker flow, read every wake from the venue's public API, become
hashed events a mechanism can fire on and a judge can cite — with the
vendor's maker-side trade field inverted in one pinned place. Before it, M31:
the company hunts for mechanisms on its own, and a scheme trades on paper.** The loop mines the event stream, brings every ranked
conjunction to every judging agent, seals each stated mechanism's forward
predictions, retires the ones that fail the instrument's own drift, and
trades the ones that earn it — five percent of the paper book, through Risk,
opened at the firing and closed at the resolution, P&L reported and never
judged. The first live view scored: a six-hour ETH short the critic had
weakened to 0.52 was right. Behind it: M30 mechanisms; M29 the world model;
M28 the adversary; M27 the service; M26 deleted the menu; M25 made the
evidence forward. No live trading, and every page says so. · 2026-09-11

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
aurelis training truth     # what is really in each scenario, and what is not
aurelis orgdev develop     # the company reorganises itself, and grades it
aurelis desk compare       # the same question on all seven desks
aurelis orgdev scale       # staff the desks, on measured evidence
aurelis training seat      # an agent in the critic's seat, weighed by the gate
aurelis strategy author    # an agent writes a rule, and it loses
aurelis strategy campaign  # it revises inside a budget, and still loses
aurelis thesis seat        # an agent picks a market and seals a view, in advance
aurelis thesis calibration # and is measured on what happened
aurelis service start      # and the company runs on its own, under a grant you recorded
aurelis world events       # what it knows that is not a price
aurelis mechanism discover # turn a mined conjunction into a tested scheme, or decline
aurelis mechanism trades   # what a calibrated scheme did on paper, through Risk
aurelis station serve      # Mission Control on http://127.0.0.1:8787/
```

Operating it: [`docs/08-operations.md`](docs/08-operations.md).

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

### Being scored on worlds where the answer is known

Research cannot tell you quickly whether an agent is any good. A strategy that
failed may have had an edge that regime-shifted; one that worked may have been
lucky; and the feedback loop is months long. So the company is also scored on
twelve generated worlds — a genuine momentum premium, names that drift up and
then delist, an effect confined to one regime, an edge the width of the spread,
and **three with nothing in them at all**, because a system that always finds
something has to be able to score badly.

The catalogue does not contain the answer key. A recipe is an instruction to a
generator, and a plant can fail to take:

```
SC-05  effect=absent       -0.0942 [-0.1118, -0.0767] over 24
         survivorship      present      +0.4665 [+0.3460, +0.5869] over 24
SC-10  effect=present      +3.2588 [+1.6304, +4.8871] over 24
         !! planted capacity_ignored; measured absent
```

An experiment gets one draw of history, exactly as a researcher gets one past.
The truth measurement gets **twenty-four**, which is the scale no experiment is
allowed, and the critic is shown a seed that is deliberately not one of them.
Where measurement disagrees with intent it is reported, never reconciled — a
catalogue that edited its intent to match its measurements would have stopped
being a check on anything.

Onboarding is what comes out of it:

```
AG-0009  CRITIC  passed      caught 7/8, 1 false alarm in 31
AG-0001  CEO     not_scored  no charter this agent holds has a scenario specialty
AG-0013  TRADE   not_scored  only 2 settled questions in this specialty; 3 needed
```

`not_scored` is a third verdict and never reads as a pass. Most of the launch
roster lands there, and saying so is the honest report — inventing a specialty
for every charter so nobody has a blank record would put fiction in the
permanent record of two thirds of the company. An agent that **fails** cannot
become active: that is a trigger on the `agents` table, so the ordinary
`set_state(ACTIVE)` path cannot get around it.

And the company's critique procedure is versioned and gated. CI runs it, and
CI also checks that the gate bites:

```
                         incumbent   candidate
real defects caught          7           4
critique.market_defects@1.1 refused — caught 7 -> 4
```

Counts, not rates: a revision that narrowed its checks would face fewer
questions, keep a perfect catch *rate*, and find strictly less.

**Three bugs the suite found in its first run**, all in code that had shipped
and been tested. `COST_UNDERSTATED` read as *present* in all three empty
worlds — tripling the cost of a rule that trades makes it worse whether or not
it ever had an edge, so as written the objection could not fail
([ADR-0011](docs/adr/0011-a-stress-test-is-not-a-correction.md)). The
`LOOKAHEAD` test was a provable no-op: its warm-up was one lookback, and every
signal already holds nothing during its own lookback. And a scenario's digest
did not cover its world, so a run cache served one scenario's artifacts for
another.

What is honestly missing: `CAPACITY_IGNORED` has no scorable scenario, and the
suite says so rather than tuning until it agreed. What is scored today is the
**procedure a charter issues**, not an agent's own judgement — the harness does
not change when agents reason for themselves, the playbook is simply replaced
by the agent.

### Changing its own shape, and grading the change

The company measures itself from its own record. The first thing that measures
says is uncomfortable: seventeen agents stand in for seventy-six charters, so
**nothing any of them produces can be attributed to any one charter**. That is
not the same as those areas being idle, and the difference is the whole reason
to split a role rather than to hire for one.

So it proposes a split — and writes down, in advance, what it expects to
happen:

```
ORG-0001  AG-0004 9 -> 7 charters
  trigger    breadth = 9
  predicted  attributable_charters up by at least 1  (locked 81d7ae814fe3 before MTG-0001)
  handover   2 charter(s) AG-0004 -> AG-0018; 0 task(s) reassigned
  new agent  AG-0018  training: not_scored
  NO_CHANGE  attributable_charters stayed at 0
```

**That change failed.** It was sensible — news and sentiment read the same
sources, so they belong on one desk — cleanly handed over, coverage conserved,
Board-approved. And seven charters is as unattributable as nine. It took a
second split, six more charters, before the metric moved:

```
ORG-0002  AG-0004 7 -> 1 charters
  IMPROVED   attributable_charters moved +1 against a predicted +1
```

Under any looser scheme the first would have gone down as a success: something
was split, the org chart looks more sensible, everyone agreed at the time. The
only reason it did not is that the prediction was **hashed before the Board
convened**, and a trigger refuses to change it afterwards
([ADR-0012](docs/adr/0012-org-changes-are-preregistered.md)). It is the
research preregistration discipline turned on the company itself.

Coverage is conserved by construction. A split is a single `UPDATE` moving
charter rows, never a delete and an insert, so no charter is held by nobody at
any instant and none by two people. The database refuses every deletion that
would orphan one — including the cascade from retiring an agent, which means
**handover is the only way out of the company**:

```
sqlite> DELETE FROM agents WHERE ref = 'AG-0004';
Aurelis: that is the last agent holding this charter. Coverage moves, it is
never dropped -- hand it over first (ADR-0003).
```

### Does more agents mean better?

`CLAUDE.md` §16 says not to assume it. M11 answers it with counts, by sitting
panels of roles in front of M10's twelve worlds:

```
Does adding an adversarial researcher reduce false discoveries?
    research only            caught 4/5, false alarms 1/26
    research + adversarial   caught 7/8, false alarms 1/31   -> treatment_better

Does a second critic with the same procedure add anything?
    one critic               caught 7/8, false alarms 1/31
    two critics              caught 7/8, false alarms 1/31   -> no_difference
```

The adversarial researcher helped — but not because it is adversarial. Its
specialty covers three defects nobody else in the room was asked about. A
second seat holding a specialty the room already has moves nothing at all, and
three narrow specialists whose specialties union to a generalist's score
exactly what the generalist scores. **More agents help only when they widen
what the room is asked.** Headcount is not capability; coverage is.

### Seven desks, and the number that makes them comparable

A desk is not a label on an agent. It is a **clock**, a **cost model**, a
**liquidity ceiling** and a set of **risk limits**, and those differ enough
between asset classes that sharing them would be wrong everywhere:

```
desk          calendar  bars/yr  round trip  material size  gross  short
Crypto        24/7         8760        40bps      $500,000     2x   yes
Equities      XNYS         1638        16bps    $2,000,000     2x   yes
Options       XNYS         1638       224bps      $250,000     1x   yes
Futures       CME          5796         7bps   $10,000,000     3x   yes
Commodities   CME          5796        21bps    $2,000,000     2x   yes
FX            24/5         6240         4bps   $20,000,000     5x   yes
Memecoins     24/7         8760       760bps        $5,000     1x    no
```

The clock is the one that had been quietly missing. The engine reported Sharpe
as `per_bar`, which was honest and useless: the same 0.05 is an annualised 4.7
on crypto and 2.0 on the NYSE, so an archive that ranked them together would be
ranking by **sampling frequency**. Every cross-desk figure is now converted
through its own desk's calendar, with the factor printed beside it, and a
comparison that cannot be made is refused rather than fudged:

```
n_trades across desks: a trade count on an hourly desk and one on a daily desk
are different questions, not the same question at two scales.

mismatched windows: crypto was measured over 2,190 bars and equities over
10,950. Annualisation makes the frequencies comparable; it does nothing about
the windows.
```

### A research budget in bars is not a budget

State a claim annualised — "a Sharpe of 1" means the same thing to everyone.
Converting it down to each desk's per-bar minimum effect divides by
`sqrt(periods per year)`, so a fast-sampling desk chases a smaller effect and
needs more bars. The two cancel exactly:

```
desk          per-bar effect  bars needed  years
crypto            0.01068435       33,655   3.84
equities          0.02470831        6,295   3.84
futures           0.01313517       22,268   3.84
fx                0.01265924       23,974   3.84
```

**The same 3.84 years on every desk, and a factor of five in bars.** Handing
every desk "1,200 bars" gives crypto seven weeks and equities nine months, and
underpowers whichever desk samples fastest while looking scrupulously
even-handed. Budgets are stated in years now.

### What is not there

**No desk has a live data feed.** Every one runs on fixtures — deterministic,
offline, shaped like the desk but not a market. The readiness checklist records
that as `PROVISIONAL` rather than letting it read as a pass, the caveat is
carried on the opening record, and it is repeated on every desk page. A desk
cannot quietly graduate from "open on fixtures" to "open".

The options desk is open and the engine cannot compute a single greek. That is
a typed refusal, not a zero: it can be researched as a price series and not as
an options book.

And building the fixtures caught two bugs that were entirely silent. **Tick
size is a desk property.** At a cent tick an FX rate of 1.00 never moved and a
memecoin priced at four thousandths of a cent quantized to zero, so two of the
seven desks produced perfectly flat series — and the engine ran, the metrics
computed, and the verdict rule said `UNDERPOWERED` without anything anywhere
reporting that the input had been a constant. "Prices move" is a readiness
check now, and a desk that fails it does not open.

### Growing to seven desks, on evidence

A charter is not one job. Thirteen of the seventy-six are meaningfully
different per market — a Technical Analyst on Options and one on FX share a
remit and differ in everything else — so with seven desks open the company owes
**154 jobs, not 76**. ADR-0004 promised that second dimension in M1;
`Charter.desk_specific` existed and nothing read it until M13, which is why
opening six desks in M12 gave the existing analyst six more markets rather than
giving six desks an analyst.

Made countable, "this desk is unstaffed" becomes a measured trigger, and the
desks are staffed the way everything else here is decided:

```
before: 76/154 slots held; 78 unstaffed
  crypto         13/13
  equities        0/13
  options         0/13     ...

desk          change     hired   unstaffed   effect
commodities   ORG-0001       5   13 -> 0     improved
equities      ORG-0002       5   13 -> 0     improved
...
17 -> 47 agents over 6 desks; 78 -> 0 unstaffed slots of 154
```

**Forty-seven, not eighty.** Each desk got one generalist per department with
desk-specific charters, exactly as the launch roster staffed crypto. A desk
running on fixtures generates no load, and hiring a specialist per charter to
reach a headline number is the assumption `CLAUDE.md` §16 exists to forbid.

So the roadmap's "100+ agents" is proved as what it actually is — a claim about
the software, not about headcount. A test hires into all 154 slots, splitting
the launch generalists down through the company's own fission mechanism, and
checks that coverage stays intact, authority still resolves and the write-scope
guards still refuse.

### The queue was doing work twice

`claim` selected a task and then wrote `CLAIMED` onto it, documented as safe
because of Postgres' `SKIP LOCKED` and SQLite's single-writer model. The second
half was false — SQLAlchemy opens a DEFERRED transaction on SQLite, so the
SELECT took no lock at all:

```
tasks=40 workers=8
claims=53 distinct=40
DOUBLE-CLAIMED: TSK-0006, TSK-0007, TSK-0011, TSK-0019, TSK-0031, ...
errors: 0
```

Thirteen tasks done twice, each drawing its own budget, and **no error
anywhere**. The write is a compare-and-set now — conditional on the row still
being queued, with the affected-row count deciding — which is correct on every
dialect and does not depend on an isolation level. Eight threads against forty
tasks is a test, not a docstring.

### Backups that are checked

```bash
aurelis db backup /backups/today
aurelis db restore /backups/today -w /new/workspace
```

Never a file copy: a copy of `aurelis.db` taken mid-transaction opens without
complaint and is missing the last write. And a restore that produces a database
which opens is not a restore, so restore re-verifies the hash chain, rehashes
every artifact against its name, and compares both against a manifest. A
tampered blob is refused:

```
1 artifact(s) whose bytes no longer hash to their name: ['1233d4535383']
```

### An agent in the author's seat

M8 built the surface an agent would author a strategy through and refused, on
purpose, to provide any function that promotes a hypothesis into one — the
company is meant to *create* an edge, not sift a corpus for one. What it did
not have was an agent. M15 is the agent.

```bash
aurelis strategy author
```

```
what it chose   momentum, one-week lookback, two-percent threshold, long only
                1 of 72 reachable designs, picked before anything was run

total return    0.026        always_long returned 0.243
cost drag       0.092        it paid this and did not earn it back
verdict         UNDERPOWERED settling the claim needs ~15 years of hourly bars
declared cells  72           the space it searched, not the design it ran
```

**The authored design did not beat holding the asset.** A rule that cannot beat
buying and holding has not found anything, and one that cannot beat doing
nothing has found less. That is the result, reported rather than tuned away —
and the system was built so that it could be.

The interesting design decision is the denominator. Authoring from a menu is
cheap, so a company that lets an agent author until something passes has built
a parameter miner with a rationale field. `declared_cells` is therefore **72,
not 1**: the agent was shown the alternatives, nothing in the record can
establish which it implicitly weighed, and understating a false-discovery
denominator manufactures confidence out of arithmetic. A second attempt costs
the family a second 72.

Costs, the universe and the warm-up are not on the menu. They are three of the
defects M10 scores the company's own critic on catching, and an agent that
could author them would be manufacturing exactly the result the other half of
the company exists to refuse.

### And what the search costs

M15 authored once and stopped, because a revision loop is where authoring turns
into mining. M16 is the loop with the stopping rule attached.

```bash
aurelis strategy campaign
```

```
attempt 1   one-week lookback      sharpe  0.0050   return  0.026
attempt 2   three-day lookback     sharpe  0.0260   return  0.202   <- best
attempt 3   one-day lookback       sharpe -0.0342   return -0.209
attempt 4   six-hour lookback      sharpe -0.0674   return -0.226
attempt 5   + half-percent floor   sharpe -0.1002   return -0.547

best observed        0.0260   and it beat holding the asset
expected best of 96  0.0538   from noise alone
surplus             -0.0278   the campaign found nothing
```

The budget and the criterion are hashed before the first design exists, and a
database trigger refuses to change them once an attempt has run. That is what
buys the agent the right to see its own results at all: **learning from a result
is allowed exactly to the extent that the learning was budgeted for.**

Then the search is subtracted. Take the best of *n* designs in a space where
nothing has an edge and you do not get zero — you get the largest of *n* draws
from the estimator's noise. Sweeping all 72 designs says the same thing without
an agent involved: the best measures 0.0274 against an expected best of 0.0516.
**Searching harder raises the bar faster than it finds anything.**

### An agent in the critic's seat

M10 built the instrument for measuring judgement and used it on a *procedure* —
numeric thresholds over the closed defect taxonomy. Its docstring named the
gap: the harness would not change when agents reasoned for themselves, the
playbook would simply be replaced by the agent.

```bash
aurelis training seat
```

```
                caught   missed   false alarms   effect calls
playbook          7/8         1         1/31          10/11
agent AG-0009     8/8         0         8/31          10/11

REFUSED  caught 7 -> 8, false alarms 1 -> 8 — it finds more and cries wolf
more. Which is better is a policy question, and the gate refuses rather than
deciding one.
```

The agent caught **everything the suite plants**, including the defect the
shipped procedure misses. It also objected to eight specifications that did not
have a defect. The regression gate compares on counts and refused it — on
arithmetic, not on taste. **Finding more is not the same as being better.**

The seat is shut on four sides. The answer set is closed, so a critic cannot
invent a defect it could not be scored against. The justification is
figure-checked, so an agent that reasons using a number nobody gave it is
rejected. `nothing` is always available, because a surface with no abstention
produces a critic that finds something every time. And a turn that cannot be
read alleges nothing — a critique nobody could act on is not a critique.

**What sits behind the seat here is not a model.** Every model call in this
repository runs against the mock provider, so a deterministic stand-in supplies
the answers; what is exercised is the machinery. Point the runtime at a real
provider and the same code path asks a real model. Every report says so, and a
test asserts the caveat is present.

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
| `aurelis strategy author` · `strategy campaign` | what the company tried to build, and what survives the search |
| `aurelis model routes` · `model tiers` | which model each role reaches, and what generalists cost |
| `aurelis model check` · `model rehearse` | one real call; and whether a seat's answers are usable at all |
| `aurelis orgdev retier` | the company splits the agent paying most for a model it did not need |
| `aurelis mandate standard` · `mandate assess` | what it must show before asking to trade, and whether it can |
| `aurelis data fetch` · `data snapshots` | the one command that reaches a market, and what it recorded |
| `aurelis research replicate REG-0001` | re-test a locked result under one declared variation |
| `aurelis trading readiness` · `trading deploy` | what stands between an authored version and a paper book |
| `aurelis trading paper` | walk the snapshot's held-out tail and measure the gap |
| `aurelis research defects` | every market defect and how it is settled |
| `aurelis tick` · `aurelis doctor` | advance the working day; check the workspace |
| `aurelis run` | the company picks its own next action from its own mandate, and stops |

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
| **M10** ✅ | Training scenarios | planted defects, onboarding, playbook regression |
| **M11** ✅ | Org development | fission, preregistered changes, org experiments |
| **M12** ✅ | Multi-desk | seven clocks, seven cost models, comparable research |
| **M13** ✅ | Scale & hardening | coverage per desk, staffed on evidence, a queue that counts |
| **M14** ✅ | Agents that decide | a closed answer set, figure-checked, scored by the same gate |
| **M15** ✅ | Agents that author | 72 designs, the search declared, the result negative (menu removed at M26) |
| **M16** ✅ | Budgets and corrections | revise inside a frozen budget, then pay for the search |
| **M17** ✅ | Model routing | the charter's tier picks the model, and NONE is refused |
| **M18** ✅ | A real model in the seat | 0/5 usable, then 5/5, with no guard widened |
| **M19** ✅ | Self-improvement, measured | 25 overtiered charters, six splits, and what it did not fix |
| **M20** ✅ | The mandate | ten hashed conditions, four met, and nobody interrupted |
| **M21** ✅ | Real data, real replication | a market recorded and hashed; a variation that must vary |
| **M22** ✅ | The gates get read | seven observables from the record, and a silence that is not a zero |
| **M23** ✅ | A real model, a real market | it ran, it found nothing, and the seat had been reading the answer key |
| **M24** ✅ | **It runs itself** | the mandate is the work queue, and a search is never repeated |
| **M25** ✅ | **Judgement, sealed** | views hashed before the outcome, scored after it, calibration as the measure |
| **M26** ✅ | **The menu is gone** | agents write rules in a closed language; one rule, one cell; the correction demands a margin |
| **M27** ✅ | **It runs for days** | a grant a person recorded, a wake every interval, and what broke on the record |
| **M28** ✅ | **Disagreement** | a critic attacks every view before the seal, and is scored on catches and false alarms |
| **M29** ✅ | **The world model** | entities, an immutable event stream, relations; the catalogue as the first non-price source |
| **M30** ✅ | **Mechanisms** | an agent's causal story over a mined pattern, tested by additional forward predictions or retired |
| **M31** ✅ | **The hunt, and paper** | the loop mines and brings every conjunction to every agent; a calibrated scheme trades on paper through Risk |
| **M32** ✅ | **The book and the tape** | order-book depth and taker flow as events every wake; the maker-side trap pinned by a test |
| **M33** ✅ | **The miner's evidence** | in-sample effect sizes beside the unconditional, labelled; the first real mechanism, and declines that say why |
| **M34** ✅ | **The universe** | a grant drawn from the venue's liquidity ranking by dollar notional, pegs excluded by measurement; a mechanism is tested wherever its trigger fires |
| **M35** ✅ | **Leverage** | funding and open interest from the perpetual, as events on the spot instrument; extreme funding and OI surges derived; a mechanism can fire on them |
| **M36** ✅ | **The hunt, on the station** | a page per mechanism: statement, evidence shown, predictions and outcomes, paper trades, and who declined the trigger and why |
| **M37** ✅ | **The facility in pixels** | deterministic agent avatars, LEDs and sprites that move only when a room works, progress bars of the record; generated, no assets |
| **M38** ✅ | **Conjunction triggers** | an agent may state a mechanism that fires only when the pair it was shown completes, at the second event; the evidence shows both; old seals unchanged |
| **M39** ✅ | **Episodes** | predictions whose horizons overlap are one episode across instruments; enough means 20 predictions and 10 episodes; beat the drift by both; open positions always close |
| **M40** ✅ | **Executable fills** | paper orders fill at the newest close the wake can see, never the trigger's; slippage on the record; no price as new as the trigger, no position |

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
