"""M15 — an agent authors a strategy, and the search it did is on the record.

M14 seated an agent as a critic, judging work somebody else had specified. This
is the seat the project was started for: the agent chooses the pieces of a
strategy from a closed space, in its own words, with a cited origin — and the
company preregisters the **whole space it chose from**, not the one design it
picked, before anything is measured.

The result on the crypto fixture is that the design does not beat holding the
asset. That is reported as the headline, because a system that could not
conclude this would not be worth the machinery around it.
"""

from aurelis.authoring.attempt import AuthoringOutcome, Baseline, run_authoring
from aurelis.authoring.author import (
    AuthoredStrategy,
    AuthoringRefused,
    Citations,
    StrategyAuthor,
)
from aurelis.authoring.campaign import CampaignOutcome, declared_width, run_campaign
from aurelis.authoring.design import Design, Slot, enumerate_designs, space_size
from aurelis.authoring.selection import SelectionCheck, check_selection
from aurelis.authoring.standin import scripted_author

__all__ = [
    "AuthoredStrategy",
    "AuthoringOutcome",
    "AuthoringRefused",
    "Baseline",
    "CampaignOutcome",
    "Citations",
    "Design",
    "SelectionCheck",
    "Slot",
    "StrategyAuthor",
    "check_selection",
    "declared_width",
    "enumerate_designs",
    "run_authoring",
    "run_campaign",
    "scripted_author",
    "space_size",
]
