"""``aurelis doctor`` — what is installed, what is protected, what is missing.

The report is deliberately blunt about things that are absent. An engine that
is not installed yet, a provider with no credentials, a database whose
append-only triggers were dropped: each is reported as the state it is, not
smoothed into a green tick. A doctor that always says "healthy" is worth
nothing to the person reading it at 2am.

Every check returns one of three states. ``OK`` means verified now, not
assumed. ``INFO`` means correct-but-worth-knowing — a component not needed
until a later milestone. ``PROBLEM`` means something that should be repaired,
and only these affect the exit code.
"""

from __future__ import annotations

import platform as _platform
import sys
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

import sqlalchemy as sa

from aurelis import __version__
from aurelis.core.errors import AurelisError
from aurelis.platform.db.tables import Base
from aurelis.platform.db.triggers import expected_trigger_names, verify_invariants
from aurelis.platform.llm.factory import raw_provider
from aurelis.platform.llm.pricing import PRICE_TABLE_VERSION
from aurelis.runtime import Runtime

__all__ = ["Check", "Status", "run_checks"]


class Status(StrEnum):
    OK = "ok"
    INFO = "info"
    PROBLEM = "problem"


@dataclass(frozen=True)
class Check:
    group: str
    name: str
    status: Status
    detail: str


def _optional_package(name: str, purpose: str, needed_from: str) -> Check:
    try:
        installed = version(name)
    except PackageNotFoundError:
        return Check(
            "dependencies",
            name,
            Status.INFO,
            f"not installed — {purpose} (needed from {needed_from})",
        )
    return Check("dependencies", name, Status.OK, f"{installed} — {purpose}")


def _check_environment() -> list[Check]:
    required = (3, 12)
    current = sys.version_info[:2]
    return [
        Check("environment", "aurelis", Status.OK, f"version {__version__}"),
        Check(
            "environment",
            "python",
            Status.OK if current >= required else Status.PROBLEM,
            f"{_platform.python_version()} on {_platform.system()}"
            + ("" if current >= required else " — Aurelis requires 3.12 or newer"),
        ),
    ]


def _check_dependencies() -> list[Check]:
    checks: list[Check] = []
    for name in ("SQLAlchemy", "pydantic", "typer", "rich"):
        try:
            checks.append(
                Check("dependencies", name, Status.OK, f"version {version(name)}")
            )
        except PackageNotFoundError:  # pragma: no cover - would fail at import
            checks.append(Check("dependencies", name, Status.PROBLEM, "not installed"))

    checks.append(
        _optional_package(
            "martex-quant",
            "the CRYPTO desk's research engine",
            "M4",
        )
    )
    checks.append(
        _optional_package(
            "claude-agent-sdk",
            "subscription model access",
            "M1 (the mock provider runs everything until then)",
        )
    )
    checks.append(
        _optional_package("anthropic", "metered API access", "whenever a budget is set")
    )
    return checks


def _check_workspace(runtime: Runtime) -> list[Check]:
    settings = runtime.settings
    workspace = settings.workspace
    checks = [
        Check("workspace", "home", Status.OK, str(workspace)),
        Check(
            "workspace",
            "object store",
            Status.OK if settings.object_store.is_dir() else Status.PROBLEM,
            str(settings.object_store)
            + ("" if settings.object_store.is_dir() else " — missing; run `aurelis db init`"),
        ),
        Check("workspace", "database url", Status.OK, settings.resolved_database_url),
    ]
    if not settings.strict_integrity:
        checks.append(
            Check(
                "workspace",
                "strict integrity",
                Status.PROBLEM,
                "disabled — append-only triggers are not installed. "
                "This is a development convenience and must not be used for real work.",
            )
        )
    return checks


def _check_database(runtime: Runtime) -> list[Check]:
    checks: list[Check] = []
    try:
        inspector = sa.inspect(runtime.database.engine)
        present = set(inspector.get_table_names())
    except Exception as error:  # pragma: no cover - connection failures
        return [Check("database", "connection", Status.PROBLEM, f"cannot connect: {error}")]

    expected = set(Base.metadata.tables)
    missing = sorted(expected - present)
    if not present:
        return [
            Check(
                "database",
                "schema",
                Status.PROBLEM,
                "no tables — run `aurelis db init`",
            )
        ]
    checks.append(
        Check(
            "database",
            "schema",
            Status.OK if not missing else Status.PROBLEM,
            f"{len(expected - set(missing))}/{len(expected)} tables present"
            + (f" — missing: {', '.join(missing)}" if missing else ""),
        )
    )

    with runtime.database.engine.connect() as connection:
        absent = verify_invariants(connection)
    total = len(expected_trigger_names())
    checks.append(
        Check(
            "database",
            "append-only triggers",
            Status.OK if not absent else Status.PROBLEM,
            f"{total - len(absent)}/{total} installed"
            + (
                f" — MISSING: {', '.join(absent)}. History is editable until repaired."
                if absent
                else " — history is not editable, including from raw SQL"
            ),
        )
    )

    with runtime.database.session() as session:
        verification = runtime.ledger.verify(session)
        counts = runtime.queue.counts_by_status(session)
        missing_files, corrupted = runtime.artifacts.verify(session)

    checks.append(
        Check(
            "database",
            "ledger chain",
            Status.OK if verification.ok else Status.PROBLEM,
            verification.describe(),
        )
    )
    checks.append(
        Check(
            "database",
            "artifacts",
            Status.OK if not (missing_files or corrupted) else Status.PROBLEM,
            "all recorded artifacts present and hashing correctly"
            if not (missing_files or corrupted)
            else f"{len(missing_files)} missing, {len(corrupted)} corrupted",
        )
    )
    checks.append(
        Check(
            "database",
            "task queue",
            Status.OK,
            ", ".join(f"{status}={count}" for status, count in sorted(counts.items())) or "empty",
        )
    )
    return checks


def _check_provider(runtime: Runtime) -> list[Check]:
    configured = runtime.settings.provider
    try:
        state = raw_provider(configured).availability()
    except AurelisError as error:
        return [Check("models", "provider", Status.PROBLEM, str(error))]

    checks = [
        Check(
            "models",
            f"provider ({configured})",
            Status.OK if state.available else Status.PROBLEM,
            state.detail,
        ),
        Check(
            "models",
            "response cache",
            Status.OK if runtime.settings.cache_models else Status.INFO,
            "enabled" if runtime.settings.cache_models else "disabled — every call will be billed",
        ),
        Check("models", "price table", Status.OK, f"version {PRICE_TABLE_VERSION}"),
    ]
    if configured == "mock":
        checks.append(
            Check(
                "models",
                "cost posture",
                Status.INFO,
                "mock provider: the whole company runs offline at zero cost. "
                "Switch with AURELIS_PROVIDER when real calls are wanted.",
            )
        )
    return checks


def _check_engines() -> list[Check]:
    """Report the research engines the desks will need.

    Reported from M0 even though none is used yet, because the desk roadmap is
    the thing an operator most wants to see the state of.
    """
    try:
        import_module("martex_quant")
    except ImportError:
        return [
            Check(
                "engines",
                "crypto (martex-quant)",
                Status.INFO,
                "not installed — the CRYPTO desk's engine, first needed at M4",
            )
        ]
    return [Check("engines", "crypto (martex-quant)", Status.OK, "importable")]


def run_checks(runtime: Runtime) -> list[Check]:
    """Every check, in report order."""
    return [
        *_check_environment(),
        *_check_dependencies(),
        *_check_workspace(runtime),
        *_check_database(runtime),
        *_check_provider(runtime),
        *_check_engines(),
    ]
