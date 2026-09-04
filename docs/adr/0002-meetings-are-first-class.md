# ADR-0002 — Meetings are first-class, structured, and budgeted

Status: accepted · 2026-09-04
Replaces an earlier draft that proposed removing conversation entirely.

## Context

`CLAUDE.md` §7 makes meetings first-class objects. Aurelis is meant to be a
company where agents brainstorm, argue, invent and decide together — not a
pipeline that passes typed records between stages.

The known risks of LLM agents in conversation are real: agreement cascades,
unbounded cost, persuasion beating evidence, fabricated figures, endless loops,
and meetings that produce nothing. An earlier draft resolved these by deleting
conversation. That resolution was rejected: it removes the mechanism the
company is built around.

## Decision

**Meetings are first-class, with real multi-round discussion and a full kept
transcript.** The risks are handled by protocol and by mechanism, not by
removing the meeting.

Every meeting runs seven phases (`docs/03-meetings.md` §3):

```
CONVENE → BRIEF → FORECAST → OPENING → EXCHANGE → CHALLENGE → SYNTHESIS → DECIDE
```

Eleven meeting types (Kickoff, Standup, Brainstorm, Research Review, Debate,
Strategy Committee, Risk Committee, Incident Review, Retrospective, Board,
All-Hands). **Kickoff and Retrospective are mandatory** on every mission and
project — enforced by the mission state machine, which cannot leave `PLANNING`
without a kickoff or reach `CLOSED` without a retrospective.

The mechanisms that make them work:

| Risk | Mechanism |
|---|---|
| Agreement cascade | Private forecasts recorded **before** anyone speaks; randomised opening order; adversarial roles on a different model family |
| Unbounded cost | Token budget and round cap declared at convene, enforced per turn, tiered by phase |
| Persuasion over evidence | Every numeral must trace to the evidence pack or a tool result, or the turn is rejected |
| Unresolvable argument | Every objection carries a **discriminating test** — an executable spec that would settle it. The Chair runs it, in the meeting. |
| Consensus by attrition | Dissent is a permanent stored field on the Decision |
| Theatre | Productivity metric per meeting and per Chair: ≥1 typed state change or the meeting is logged unproductive |

The Chair is **mostly deterministic** — evidence packs, round enforcement,
speaker selection, claim extraction, task creation, forecast scoring all cost
nothing. Only synthesis and convergence judgement use a model.

## Rationale

The discriminating-test requirement is the load-bearing part. It converts
"I think this is overfit" into "re-run with a point-in-time universe and Sharpe
drops below 1.0," which the Chair dispatches and everyone sees the answer to.
Debate then terminates in evidence rather than in a token budget — which
satisfies `CLAUDE.md` §1.3 through the mechanism rather than by asking agents
to be fair.

Keeping the transcript matters independently: reading why the company believes
something is one of the things Mission Control exists for.

## Consequences

- Meetings are the largest single cost centre, and the budget system is built
  around that from the start.
- The transcript is a durable, queryable, renderable object — every turn typed,
  every claim extracted, every position change recorded.
- Attendance scales the way real companies scale: required, contributing, and
  observing. At 100 agents a Research Review still has six people in the room.
- If a meeting type keeps coming out unproductive, its protocol changes or it
  stops being held — decided on the metric, not on taste.
