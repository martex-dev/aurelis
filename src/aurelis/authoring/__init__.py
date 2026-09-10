"""An agent writes a rule, and the company measures it.

M14 seated an agent as a critic, judging work somebody else had specified. M15
seated one as an author with a menu of 72 designs; M26 took the menu away. The
agent now writes the rule itself, in the company's rule language, in its own
words, with a cited origin — and the company preregisters the rule before
anything is measured, one declared cell per rule.

The result on the crypto fixture is that the rule does not beat holding the
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
from aurelis.authoring.selection import SelectionCheck, check_selection
from aurelis.authoring.specs import BASELINES, baseline_spec, render_spec
from aurelis.authoring.standin import scripted_author

__all__ = [
    "BASELINES",
    "AuthoredStrategy",
    "AuthoringOutcome",
    "AuthoringRefused",
    "Baseline",
    "CampaignOutcome",
    "Citations",
    "SelectionCheck",
    "StrategyAuthor",
    "baseline_spec",
    "check_selection",
    "declared_width",
    "render_spec",
    "run_authoring",
    "run_campaign",
    "scripted_author",
]
