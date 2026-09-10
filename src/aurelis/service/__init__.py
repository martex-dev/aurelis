"""The company running for days: waking on a schedule, recording what broke.

Everything before this was a command somebody typed. `aurelis run` decides
what the company does next, but a person still starts it, and the one thing
it will not do — fetch data — is the thing a forward record cannot accumulate
without. M25's views resolve only when a recording covers their horizon, and
nothing recorded anything unless a person did.

This package is the service that wakes on an interval and does the working
day: fetch fresh recordings for the instruments a person has *granted*,
settle every view a recording now covers, seat the judges again, and write
down what happened — including what failed. A vendor that is down, a model
that is out of allowance, a malformed payload: each is an alert on the record
and the service carries on. A service that stopped on the first bad hour would
never see a second.

Two boundaries, both stated because both matter.

**Fetching still needs a person.** The loop does not fetch (ADR-0025); the
service fetches only under a grant a person recorded once, naming the vendor
and the instruments, on the ledger, revocable and never editable. A standing
grant is a decision somebody made, not a flag an agent set.

**It still does not trade.** No live adapter exists (ADR-0006), and this
package adds none.
"""

from aurelis.service.grants import Grants
from aurelis.service.loop import Service, ServiceOutcome, cycle_once, serve

__all__ = ["Grants", "Service", "ServiceOutcome", "cycle_once", "serve"]
