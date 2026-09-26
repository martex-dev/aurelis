# ADR-0059 — A method is judged by the mechanisms too

Status: accepted · 2026-09-26

## Context

M48 (ADR-0049) gave every judging agent a written, versioned method that it
carries to every seat, and replaced a method whose forward views scored worse
than a coin toss. ADR-0049 recorded what it left undone: "The
mechanism-discovery seat carries the method but its fitness is not yet
measured by the mechanisms the agent states."

So an agent could state mechanism after mechanism that the company tested and
retired, and keep its method for as long as its views were no worse than
chance. Discovery is where the company looks for an edge. It was also the one
seat whose results never reached evolution.

## Decision

- **Discovery fitness** (`evolution/methods.py`) counts the mechanisms an
  agent stated since its method was adopted and has been decided on: those
  that became candidate schemes and those that were retired. Mechanisms
  still gathering are not decided.
  - Below five decided mechanisms, the record is unproven.
  - At five or more with none a scheme, it is failing.
  - With at least half of them schemes, it is thriving.
  - Anything else is chance.
- **Either record can fail a method.** The daily evolution rewrites a method
  whose views fail, as before, or whose mechanisms fail. The method's text is
  shared by every seat, so one rewrite serves both.
- **The teacher fits the failure.** When views fail, the best-calibrated
  colleague writes the replacement. When mechanisms fail, a colleague whose
  own mechanisms thrive writes it. With no such colleague, the agent revises
  its own. The material shows why its retired mechanisms were retired.
- The `org.evolution_ran` event records every agent's discovery verdict next
  to its view fitness.

## Consequences

- The company's search for mechanisms now feeds back into how its agents
  search. That was the last seat whose outcome did not.
- Five decided mechanisms is a low floor. The bar is "none became a scheme",
  so a method is replaced for producing nothing, never for producing less
  than a colleague.
- **Not done.** Methods are still not tried against each other on the same
  material. A replacement is judged against its predecessor's record, not
  against an alternative written at the same time.
