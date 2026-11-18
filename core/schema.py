"""schema.py

Response envelope, error body, health and API-key models shared by every route.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = Field(description="degraded: the document parser has not loaded.")
    docling_loaded: bool = Field(description="PDFs and images can be parsed (text files do not need it).")


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_admin: bool = False
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyInfo(BaseModel):
    id: int
    name: str
    prefix: str
    is_admin: bool
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreated(BaseModel):
    key: str = Field(description="Shown once. Store it securely.")
    api_key: ApiKeyInfo


class ApiKeyList(BaseModel):
    count: int
    keys: list[ApiKeyInfo]
