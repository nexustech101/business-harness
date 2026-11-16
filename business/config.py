"""business/config.py

The `business` section of `config/model_config.yml` (the rest of the file is `agent.config`): the workspace
database (shared with `ConnectorHub`), the secrets key's environment variable, the public URL for OAuth
redirects, the context budgets of role assistants, and the partner's prompt and tool rounds.

*Usage:*
>>> config = load_business_config(Path("config/model_config.yml"))
>>> config.database, config.secrets_key()      # key: None when the variable is unset
(PosixPath('/.../data/business.db'), None)
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field

from agent.config import read_yaml
from core.config import PROJECT_ROOT
from library.config import StrictConfig


class ContextBudgets(StrictConfig):
    """Maximum characters per context layer (see business/context.py)."""

    business: int = Field(default=4000, ge=500)
    role: int = Field(default=10_000, ge=500)
    team: int = Field(default=1500, ge=200)
    notes: int = Field(default=3000, ge=200)


class PartnerSettings(StrictConfig):
    max_tool_rounds: int = Field(default=6, ge=0, le=20)
    system_prompt: str = Field(min_length=1)


class BusinessConfig(StrictConfig):
    database: Path = Path("data/business.db")
    secrets_key_env: str = "BUSINESS_SECRETS_KEY"
    public_url: str = "http://localhost:8000"
    assistant_prompt: str = Field(min_length=1, description="Leads every role assistant's business layer.")
    context: ContextBudgets = Field(default_factory=ContextBudgets)
    partner: PartnerSettings

    def secrets_key(self) -> bytes | None:
        """The Fernet key (base64) from `secrets_key_env`; None when unset (the hub then uses `key_file`)."""
        value = os.environ.get(self.secrets_key_env, "").strip()
        return value.encode() if value else None

    @property
    def key_file(self) -> Path:
        """Where the hub keeps a generated key when `secrets_key_env` is unset: beside the database."""
        return self.database.with_name("secrets.key")


def load_business_config(path: Path) -> BusinessConfig:
    """Validate the `business` section; a relative `database` is resolved against the project root."""
    config = BusinessConfig.model_validate(read_yaml(path).get("business") or {})
    if not config.database.is_absolute():
        config.database = PROJECT_ROOT / config.database
    return config
