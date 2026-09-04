"""Configuration.

Resolution order, outermost wins: explicit argument, then environment
(``AURELIS_*``), then ``.env``, then the defaults here.

Defaults are chosen so that a fresh clone runs with no configuration at all:
SQLite in the working directory, the mock model provider, and no credentials
anywhere. That is what lets CI exercise the whole company at zero cost, and it
means the first thing a new operator does is see it work rather than fill in a
form.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "load_settings"]

WORKSPACE_ENV = "AURELIS_HOME"


class Settings(BaseSettings):
    """Everything the platform needs to start."""

    model_config = SettingsConfigDict(
        env_prefix="AURELIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- workspace -------------------------------------------------------

    home: Path = Field(
        default=Path("."),
        description="Workspace root. The database, object store and logs live under it.",
    )

    database_url: str = Field(
        default="",
        description="SQLAlchemy URL. Empty means SQLite at <home>/aurelis.db.",
    )

    # --- model access ----------------------------------------------------

    provider: str = Field(
        default="mock",
        description=(
            "Model provider: 'mock' (offline, free, deterministic), "
            "'agent_sdk' (Claude subscription), or 'anthropic_api' (metered)."
        ),
    )

    cache_models: bool = Field(
        default=True,
        description="Cache model responses by pinned model version and request hash.",
    )

    # --- budgets ---------------------------------------------------------

    company_budget_usd: str = Field(
        default="0",
        description=(
            "Company-wide money allowance, as a decimal string. "
            "Zero means unmetered-by-money, which is correct under a "
            "subscription: token limits still apply."
        ),
    )

    company_budget_tokens: int = Field(
        default=0,
        description="Company-wide token allowance. Zero means no token cap.",
    )

    # --- behaviour -------------------------------------------------------

    strict_integrity: bool = Field(
        default=True,
        description=(
            "Install append-only triggers and verify the chain on startup. "
            "Turning this off is a development convenience and is reported by "
            "`aurelis doctor` as a degraded state."
        ),
    )

    # --- derived ---------------------------------------------------------

    @property
    def workspace(self) -> Path:
        return self.home.expanduser().resolve()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+pysqlite:///{(self.workspace / 'aurelis.db').as_posix()}"

    @property
    def object_store(self) -> Path:
        return self.workspace / "objects"

    def ensure_workspace(self) -> Path:
        """Create the workspace directories. Idempotent."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.object_store.mkdir(parents=True, exist_ok=True)
        return self.workspace


def load_settings(**overrides: object) -> Settings:
    """Build settings, with explicit overrides winning over the environment."""
    return Settings(**overrides)  # type: ignore[arg-type]
