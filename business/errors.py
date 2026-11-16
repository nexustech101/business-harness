"""business/errors.py

Domain errors of the business workspace; `api/errors.py` maps each to an HTTP status and code.
"""

from __future__ import annotations


class InvalidSpec(ValueError):
    """An assistant spec that cannot be stored as is (422 invalid_assistant)."""


class NotActive(RuntimeError):
    """The assistant is a draft or paused (409 assistant_inactive)."""


class AlreadyDecided(RuntimeError):
    """The approval was already decided, or another decision is executing it (409 already_decided)."""


class OutdatedWorkspace(RuntimeError):
    """The workspace database holds tables of another schema version (500 outdated_workspace)."""
