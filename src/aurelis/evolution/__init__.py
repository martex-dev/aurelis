"""The company evolves how its agents think, on the forward record.

Every judging agent has a *method*: a short statement, in its own words, of
how it forms a view -- what it looks at, when it abstains, how it sets its
confidence. Methods are versioned and append-only, and the current one is
part of the agent's identity at every seat.

Once a day the company measures each method's fitness: the Brier score of the
views the agent sealed under it, forward, against 0.25 for a coin toss, with
its standard error. A method significantly worse than a coin toss is replaced.
The best-calibrated colleague writes the replacement, from its own method and
the failing agent's worst calls; if nobody is doing better than chance, the
agent revises its own method from its own mistakes. Each new method records
the fitness of the one it replaced, so whether the change helped is on the
record the day the new method has enough views to say.

This is the brief's "they evolve" on the only evidence that cannot be
overfitted: judgements sealed before their outcomes existed.
"""
