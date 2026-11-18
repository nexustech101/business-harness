"""Shared fixtures.

The API-key database URL must point at a throwaway file *before* `core` is
imported, because `registers` binds models to it at import time. Isolation
comes from `fresh_key_db`: every test module starts with empty tables.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="business-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import pytest  # noqa: E402

from core.config import Settings, get_settings  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def fresh_key_db():
    """Drop and recreate the API-key tables before each test module. Per module, not per test, so a
    module can keep one app and key for all its tests."""
    import core.models  # noqa: F401  (registers the tables on `db`)
    from core.db import db, init_db

    for manager in db.all().values():
        manager.drop_schema()
    init_db()


@pytest.fixture(scope="session", autouse=True)
def no_real_connector_hub():
    """`create_app` builds a `ConnectorHub` from the config when none is injected (e.g. `scripts.openapi.render`,
    `tests/test_web.py`); tests get a `FakeHub` there instead. The real hub is tested by constructing it."""
    import api.app
    from tests.fakes import FakeHub

    real = api.app.ConnectorHub
    api.app.ConnectorHub = lambda database, secrets_key, public_url, key_file=None: FakeHub()
    yield
    api.app.ConnectorHub = real


def make_test_app(settings: Settings | None = None, parser=None, load_models: bool = False, assistant=None,
                  business=None, connectors=None):
    """(app, raw admin key). Creates tables and an admin key directly. `assistant`: (library, assistant).
    `business`: the workspace; by default one on a fresh temporary database with `connectors` (default
    `tests.fakes.FakeHub()`) and the assistant's library and chat model."""
    import agent
    from agent.config import load_config
    from api.app import create_app
    from business.service import Business
    from core.auth import create_api_key
    from core.db import init_db
    from tests.fakes import FakeHub, business_config

    init_db()
    raw, _ = create_api_key("test-admin", is_admin=True)
    settings = settings or get_settings()
    if business is None:
        assistant = assistant or agent.build(load_config(settings.assistant_config))
        library, chat = assistant[0], assistant[1].chat
        connectors = connectors or FakeHub()
        business = Business(business_config(Path(tempfile.mkdtemp(dir=_TMP))), library, chat, connectors)
    app = create_app(settings, parser=parser, load_models=load_models, dispose_db_on_shutdown=False,
                     assistant=assistant, business=business)
    return app, raw

