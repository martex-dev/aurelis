"""A second process waits for the database instead of failing on the lock.

The operator recorded two grants while the service was mid-wake, and both
commands died on ``database is locked`` after SQLite's default five seconds:
a seat holds a write transaction for as long as a model call takes. Every
engine now waits up to :data:`aurelis.platform.db.session.BUSY_TIMEOUT`
seconds for the lock before giving up, so a command issued during a wake
waits for the wake rather than failing.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

from aurelis.platform.db.session import BUSY_TIMEOUT, create_engine


def _hold_lock(url: str, seconds: float) -> None:
    holder = create_engine(url, busy_timeout=1)
    with holder.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        connection.exec_driver_sql("INSERT INTO t (v) VALUES (1)")
        time.sleep(seconds)
        connection.exec_driver_sql("COMMIT")
    holder.dispose()


def test_a_command_waits_for_a_locked_database_instead_of_failing(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'busy.db'}"
    setup = create_engine(url)
    with setup.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE t (v INTEGER)")
    setup.dispose()
    assert BUSY_TIMEOUT >= 60, "long enough to outlast a seat's model call"

    # Another connection holds the write lock for two seconds; a writer that
    # waits one second fails, a writer that waits longer gets through.
    thread = threading.Thread(target=_hold_lock, args=(url, 2.0))
    thread.start()
    time.sleep(0.3)
    impatient = create_engine(url, busy_timeout=0.2)
    started = time.monotonic()
    with pytest.raises(sa.exc.OperationalError, match="locked"), impatient.begin() as connection:
        connection.exec_driver_sql("INSERT INTO t (v) VALUES (2)")
    assert time.monotonic() - started < 1.5
    impatient.dispose()

    patient = create_engine(url, busy_timeout=10)
    with patient.begin() as connection:
        connection.exec_driver_sql("INSERT INTO t (v) VALUES (3)")
    thread.join()
    with patient.connect() as connection:
        rows = connection.exec_driver_sql("SELECT v FROM t ORDER BY v").fetchall()
    patient.dispose()
    assert [r[0] for r in rows] == [1, 3], "the patient writer waited for the holder and wrote"
