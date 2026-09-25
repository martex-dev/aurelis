"""Who the company follows on social platforms, and why (M50).

A source in the catalogue is a *kind* of reading: Reddit's new posts, a
Telegram channel's preview, an X search. A target is *whom* it reads there:
one Telegram channel, one X account, one Discord channel. Targets come from
three places, and every one says where it came from:

* **token links**: a memecoin followed on the dex desk publishes its own X
  account and Telegram channel on DEX Screener, and the company follows them
  while it follows the token;
* **the operator**, with ``aurelis social follow``;
* **an agent**, who says why.

A follow or a drop is a row, never an edit. The newest row for a handle is its
state, so the record shows who followed what, when, and why it was dropped.
"""

from aurelis.social.targets import (
    PLATFORMS,
    Target,
    active_targets,
    drop_target,
    follow_target,
    normalise_handle,
)

__all__ = [
    "PLATFORMS",
    "Target",
    "active_targets",
    "drop_target",
    "follow_target",
    "normalise_handle",
]
