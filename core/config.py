"""config.py

Runtime settings, read once from the environment / `.env`.

*Usage:*
>>> from core.config import settings
>>> settings.max_upload_mb
20
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    # --- API -----------------------------------------------------------------
    app_name: str = "Business Partner API"
    log_level: str = "INFO"
    log_json: bool = True
    # The file keeps its original name so existing installs keep their keys.
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'tax_document_database.db'}"
    # Lets the very first POST /api-keys run unauthenticated. Off by default:
    # create the first admin key with `uv run main.py create-key --admin`.
    allow_key_bootstrap: bool = False

    # --- Rate limits (requests per window, per API key, per route) -----------
    library_rate_calls: int = 30  # document uploads
    library_rate_seconds: int = 60
    search_rate_calls: int = 120
    search_rate_seconds: int = 60
    assistant_rate_calls: int = 30
    assistant_rate_seconds: int = 60

    # --- Models, library and workspace (see the YAML file) ---------------------
    assistant_config: Path = PROJECT_ROOT / "config" / "model_config.yml"

    # --- Uploads ---------------------------------------------------------------
    max_upload_mb: int = 20  # per file
    max_pages: int = 100  # per PDF

    # --- Upload jobs (one job = one document being parsed and indexed) ----------
    max_concurrent_jobs: int = 2  # running at once; each holds its file in memory
    max_queued_jobs: int = 8  # waiting beyond this get 503 busy

    # --- Docling ---------------------------------------------------------------
    docling_device: str = "auto"  # auto | cpu | cuda | mps
    docling_threads: int = 4
    docling_tables: bool = False  # TableFormer; the index reads raw text lines instead
    docling_timeout_s: float = 120.0
    docling_artifacts_path: Path | None = None  # pre-downloaded weights (offline)
    docling_max_concurrency: int = 1  # conversions in flight; models are CPU/GPU bound
    docling_warmup: bool = True  # run one tiny conversion at startup


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
