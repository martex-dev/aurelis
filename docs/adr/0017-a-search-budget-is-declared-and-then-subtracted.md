# ADR-0017 — A search budget is declared, and then subtracted

Status: accepted · 2026-09-07

## Context

M15 put an agent in the author's seat and stopped after one attempt. The
reasoning was written down at the time: a revision loop is exactly where
authoring turns into mining, and it should not be added without deciding first
what stops it.

The loop is worth having. A company that cannot respond to its own measurements
is not learning, and "authors one design and never looks at the result" is not a
research organisation. But the failure mode is not subtle. Authoring from a menu
costs seconds. An agent allowed to revise until something passes will find
something that passes, because a wide enough search always does — and each
revision will arrive with a paragraph of reasoning attached, which makes the
mining harder to see, not easier.

M15 also left the correction half-done. It declared how wide a search was and
summed the declared cells per family, which is the right bookkeeping. Nothing
then applied it to a number.

## Decision

**A campaign declares its budget before the first design exists, and its best
result is corrected for the width of the search that found it.**

- A `Campaign` row carries `budget`, `declared_width` and `criterion`, hashed
  and locked before any attempt runs. A database trigger,
  `aurelis_campaign_plan_is_immutable`, refuses to change any of them once
  `attempts_run > 0`.
- The first attempt authors from the whole space (72 designs). Each later
  attempt **revises**: two closed questions — which one slot changes, and what
  it becomes — recorded through `Synthesis.mutate` as a new version superseding
  the last. The family is not revisable.
- `declared_width = 72 + (budget − 1) × 6`, and the campaign asserts that the
  family's summed declared cells equal it. The plan and the ledger agree, or
  the run says so.
- The headline is `check_selection`: the best Sharpe **minus** the expected
  best of `declared_width` draws from the estimator's own noise, computed from
  the standard error the run itself reported.

**Inside a declared campaign, and only there, the agent may see its own
result.** Everywhere else an author is shown structure alone.

## Rationale

### What the budget buys

The rule that a design must be chosen before any result exists is what makes
M15's preregistration a lock rather than a description. Relaxing it looks like
giving up the milestone's central guarantee.

It is not, because the guarantee has two halves and only one of them is *when*
the choice was made. The other is *how wide* the search was, and that is the
half that actually protects the number. A search whose width was declared in
advance and subtracted afterwards is honest whether the agent looked at one
result or all of them; a search whose width was not declared is dishonest even
if the agent looked at nothing. So: **learning from a result is allowed exactly
to the extent that the learning was budgeted for.**

### Why the width is the sum and not the product

M15 charged the whole space for one attempt, because nothing in the record could
establish which alternatives the agent implicitly weighed, and an unmeasurable
quantity has one defensible direction. A revision is different: it is *shown*
one slot's alternatives and can reach exactly six designs. That is measurable,
so it is measured. Charging `budget × 72` would inflate the denominator as
dishonestly as understating it deflates it — the rule was never "be
pessimistic", it was "be accurate, and when you cannot be, be conservative".

Keeping the family unrevisable is what makes this countable in advance: every
branch has exactly six one-slot neighbours, so the width does not depend on
which family the agent picks.

### Why the correction is computed here rather than called

`aurelis.engines.martex` already wraps martex-quant's deflated Sharpe, and it
is the right thing to call when installed. It is an optional extra and is absent
from the environment CI runs in. **A correction that silently does not run in CI
is a correction nobody applies.** So the expected-best half is computed from the
standard library using the same Bailey–López de Prado approximation
`expected_max_sharpe` uses, and the two agree by construction.

## Consequences

- **The campaign found something, and the correction took it away.** This is
  the result, and it is sharper than M15's:

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

  Revising *moved the number*, and the second attempt beat buy-and-hold on its
  own window — which M15's single attempt did not. Reporting that half alone
  would be a discovery. The correction says it is still below what a search of
  this width returns when there is nothing to find.

- **Four of the five attempts are worse than the one before.** The campaign is
  a walk, not a convergence, and one point on it happened to be high. A report
  that showed only the maximum would read as a search closing in on something.
  `improved` is a property on the outcome and it is false.

- **Sweeping the whole space says the same thing more strongly.** The best of
  all 72 designs measures 0.0274 against an expected best of 0.0516. Six trials
  is already enough to eat it. The answer to "should we search harder?" is that
  searching harder raises the bar faster than it finds anything.

- **The correction is conservative and says so.** It treats designs as
  independent and normal; 72 designs over one price series are correlated, which
  makes the true expected maximum smaller. So it may call a real edge nothing,
  and will not call nothing an edge. That direction is stated on every report.

- **A revision is recorded as `REFINED`, citing the component it replaces.**
  Otherwise the company could inflate what it created by changing one number
  five times.

- **The revision material nearly ate the research budget.** `revision_material`
  merged a section called `budget` into structural material that already had one
  — the bars available — so a revising agent silently lost sight of how much
  data it had. The merge now refuses on any key collision rather than trusting
  the caller to have picked a free name.

- What is *not* done: the campaign chooses its own next revision, and nothing
  else in the company reviews it. The M14 critic could sit over an authored
  version, and does not yet. And a campaign is still a single desk over fixture
  data — the correction is arithmetic about a search, not evidence about a
  market.
