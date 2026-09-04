# ADR-0005 — Training scenarios measure agents and org changes

Status: accepted · 2026-09-04

## Context

The company must improve itself: hire, split roles, promote, retrain, revise
playbooks, and know whether any of it helped. That requires being able to
measure whether an agent or an org change is *good*.

Real market research cannot supply that measurement quickly. A strategy that
failed may have had an edge that regime-shifted; one that worked may have been
lucky; and the feedback loop is months long. Grading an agent's prose with
another agent is circular.

## Decision

**A synthetic engine generates research scenarios where the answer is known in
advance**, and the company is scored on them.

Scenarios contain planted structure: a real momentum premium of a stated size,
a planted data leak, a planted survivorship bias, a regime-dependent effect —
and, in a large fraction of cases, **nothing at all**. Truth is *measured* by
running the comparison at a scale no experiment is allowed, never authored.

Three uses:

1. **Onboarding.** A newly hired agent runs the scenario suite for its
   charters before it touches live research. Its hit rate and false-positive
   rate become its starting record. An agent that cannot catch planted defects
   in its own specialty does not start work.
2. **Org experiments.** Does adding an Adversarial Researcher reduce false
   discoveries? Do three technical analysts beat two? Run the same suite with
   and without, and count.
3. **Regression.** Playbooks and capabilities are versioned; a revision that
   lowers the catch rate on the suite fails CI and does not ship.

Alongside it, two other honest signals that need no synthetic data:

- **Forecast calibration.** Every participant records a probability before
  every experiment and every meeting outcome, scored afterwards. Cheap, per
  agent, non-circular.
- **Forward paper performance.** The backtest-vs-live gap, measured per
  strategy and per desk.

## Rationale

This is what turns "the company researches itself" from an aspiration into
arithmetic. Without it, org changes are decided on impressions and agent
quality is a matter of opinion.

It also runs **entirely offline and cheaply**, which matters while the company
runs on a subscription: the scenario suite never waits on a data feed and
never touches a market API.

The suite includes scenarios with no effect because a system that always finds
something scores badly on them — which is exactly the failure mode a research
company must be able to detect in itself.

## Consequences

- The synthetic engine is real work, and it gates the org-development milestone.
- Scores are **institutional competence, not market truth**. An agent
  calibrated on planted effects may still be miscalibrated on real markets, and
  every report of a scenario score must say which it is.
- Every agent carries a scenario record alongside its live record, and Mission
  Control shows both.
- Objection types must stay a closed taxonomy, because a free-text objection
  cannot be matched against a planted defect.
