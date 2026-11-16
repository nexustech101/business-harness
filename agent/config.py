"""agent/config.py

Assistant configuration, read from `config/model_config.yml` (see the comments
there): the chat model and assistant settings, composed with the library's
embeddings and storage settings (`library.config`). Validated on load, so a
typo fails at startup instead of on the first request. API keys are read from
the environment variable each endpoint names. The `business` section belongs
to `business.config` (it sits above this package), which validates it from the
same file.

*Usage:*
>>> config = load_config(Path("config/model_config.yml"))
>>> config.chat.url, config.chat.api_key()
('http://localhost:11434/v1', None)
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import Field

from core.config import PROJECT_ROOT
from library.config import EmbeddingConfig, Endpoint, LibraryConfig, StrictConfig


class ChatConfig(Endpoint):
    temperature: float | None = Field(default=0, ge=0, le=2)  # null: not sent (models that fix it)
    max_tokens: int = Field(default=1024, ge=16)
    options: dict = Field(default_factory=dict)


class AssistantSettings(StrictConfig):
    max_tool_rounds: int = Field(default=4, ge=0, le=10)
    system_prompt: str = Field(min_length=1)


class AssistantConfig(StrictConfig):
    chat: ChatConfig
    embeddings: EmbeddingConfig
    library: LibraryConfig = Field(default_factory=LibraryConfig)
    assistant: AssistantSettings


OTHER_SECTIONS = ("business",)  # validated by business/config.py


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_config(path: Path) -> AssistantConfig:
    """Read and validate the YAML file (every section but `OTHER_SECTIONS`). Relative `library.database` /
    `library.files` are resolved against the project root."""
    raw = {k: v for k, v in read_yaml(path).items() if k not in OTHER_SECTIONS}
    config = AssistantConfig.model_validate(raw)
    for name in ("database", "files"):
        value = getattr(config.library, name)
        if not value.is_absolute():
            setattr(config.library, name, PROJECT_ROOT / value)
    return config
