"""The complete schema, in one place.

SQLAlchemy registers a table when its module is imported, so ``create_all``
only ever creates what happens to have been imported first. That makes the
shape of the database an accident of import order — and it fails in a
particularly nasty way here, because the write-scope guards install triggers on
tables by name and a missing table turns a security guarantee into an
``OperationalError`` at startup.

So the schema is an explicit list. Adding a table means adding it here, which
is a one-line change that shows up in review next to the table itself, and a
test asserts that every module defining a table appears.
"""

from __future__ import annotations

from aurelis.agents import tables as _agents
from aurelis.alerts import tables as _alerts
from aurelis.authoring import tables as _authoring
from aurelis.autonomy import tables as _autonomy
from aurelis.comms import tables as _comms
from aurelis.desks import tables as _desks
from aurelis.intel import snapshots as _snapshots
from aurelis.intel import tables as _intel
from aurelis.judgement import tables as _judgement
from aurelis.mandate import tables as _mandate
from aurelis.mechanism import tables as _mechanism
from aurelis.meetings import tables as _meetings
from aurelis.memory import tables as _memory
from aurelis.missions import tables as _missions
from aurelis.org import tables as _org
from aurelis.orgdev import tables as _orgdev
from aurelis.platform.db import tables as _platform
from aurelis.platform.db.tables import Base
from aurelis.portfolio import tables as _portfolio
from aurelis.research import tables as _research
from aurelis.risk import tables as _risk
from aurelis.service import tables as _service
from aurelis.sources import tables as _sources
from aurelis.strategy import tables as _strategy
from aurelis.trading import tables as _trading
from aurelis.training import tables as _training
from aurelis.world import tables as _world

__all__ = ["Base", "TABLE_MODULES"]

TABLE_MODULES = (
    _platform,
    _org,
    _desks,
    _agents,
    _comms,
    _intel,
    _snapshots,
    _missions,
    _meetings,
    _research,
    _memory,
    _strategy,
    _portfolio,
    _risk,
    _trading,
    _alerts,
    _training,
    _orgdev,
    _authoring,
    _autonomy,
    _mandate,
    _judgement,
    _mechanism,
    _service,
    _sources,
    _world,
)
"""Every module that defines tables, in dependency order.

The order is not required by SQLAlchemy — it resolves foreign keys itself —
but it reads as the layering does, which makes an import that points the wrong
way obvious.
"""
