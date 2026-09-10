"""The world model: entities, a typed event stream, and relations between them.

Everything the company held before this was a price series sampled at
intervals: every source served bars, every experiment walked bars, every view
was a function of past closes. The brief names the kind of thing this company
is supposed to find — *a token posted in two communities within hours while a
known-early wallet cluster starts buying* — and nothing in that sentence is a
price series. It is entities (tokens, accounts, wallets, venues), events
(posted, bought, listed, delisted), relations (belongs to, funded by, deployed
by), and conjunctions inside a time window.

This package is the first, deliberately small version of that layer.

**Entities** are things with an identity: an instrument, an asset, a venue.
They have a kind, a key, attributes, and a first-seen time.

**Events** are typed, timestamped, immutable, and hashed. An event names the
entity it is about, carries its payload, and says where it came from — a
vendor endpoint or a recording it was derived from. The table is append-only
by trigger. Price is *one* event type among many, and only its notable moments
(a volume spike, a range break) enter the stream; the bars themselves stay in
their recordings.

**Relations** are typed edges between entities, append-only, with a source.

**Queries over windows** are what make schemes expressible: the events for an
entity since a moment, and the co-occurrence of event kinds inside a window.

What enters the stream today is what the company can legitimately reach with
no credentials: the venue's own product catalogue (listings, status changes,
trading halts) and what can be derived deterministically from recordings. Every
event is a recording, hashed, exactly as bars are; research never runs against
a live endpoint.
"""

from aurelis.world.derive import derive_price_events
from aurelis.world.sources import CoinbaseProducts, sync_catalogue
from aurelis.world.store import World

__all__ = ["CoinbaseProducts", "World", "derive_price_events", "sync_catalogue"]
