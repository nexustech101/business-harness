"""schema.py

Request/response models for the HTTP API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar, Union

from pydantic import BaseModel, Field

from core.flags import Flag
from core.forms import FORMS

T = TypeVar("T")

# All form models, so OpenAPI documents every possible `fields` payload.
AnyForm = Union[tuple(FORMS.values())]  # type: ignore[valid-type]  # noqa: UP007 (built from a tuple)


class Envelope(BaseModel, Generic[T]):
    data: T


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# --- System / keys --------------------------------------------------------------


class ModelStatus(BaseModel):
    name: str
    available: bool


class HealthResponse(BaseModel):
    status: str  # ok | degraded
    docling_loaded: bool
    ollama_reachable: bool
    models: list[ModelStatus]


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


# --- Documents ----------------------------------------------------------------------


class DocumentInfo(BaseModel):
    filename: str
    media_type: str
    sha256: str
    pages: int
    text_layer: bool = Field(description="False when the document was OCR'd (scan or photo).")
    conversion: Literal["complete", "partial"] = Field(
        default="complete", description="partial: the parser reported errors; see conversion_errors.")
    conversion_errors: list[str] = Field(default_factory=list)
    missing_pages: list[int] = Field(
        default_factory=list, description="Pages no text was read from: failed, blank or unreadable.")


class ClassificationResult(BaseModel):
    document_type: str = Field(description="Supported form id, or 'unknown'.")
    label: str | None = Field(default=None, description="Human-readable form title.")
    confidence: float = Field(description="Probability tev assigned to the chosen document type.")
    probabilities: dict[str, float] = Field(
        description="Probability per option, highest first ('none' = not a supported form).")
    model: str


class ClassifyResponse(BaseModel):
    request_id: str
    classification: ClassificationResult
    document: DocumentInfo | None = Field(default=None, description="Omitted when text was classified.")
    timings_ms: dict[str, int]


class ValueSource(BaseModel):
    """Where a value was read: the printed label it sits under, and its position."""

    label: str | None = Field(description="Printed label the value sits under; null for unlabeled text.")
    page: int
    box: tuple[float, float, float, float] = Field(
        description="left, top, right, bottom; page width is 1000 units, origin top-left.")


class ValidationReport(BaseModel):
    valid: bool = Field(description="True when nothing was dropped, flagged or inconsistent (no flags).")
    flags: list[Flag] = Field(description="What a reviewer should check, each with its field path and code.")
    fields_found: int
    fields_total: int
    sources: dict[str, ValueSource] = Field(
        default_factory=dict, description="Field path -> where each amount, TIN and table row was read.")


class ExtractResponse(BaseModel):
    request_id: str
    document_type: str
    form_name: str
    classification: ClassificationResult
    fields: AnyForm  # type: ignore[valid-type]
    validation: ValidationReport
    document: DocumentInfo
    extraction_model: str
    timings_ms: dict[str, int]


class FormResult(BaseModel):
    """One form found in an uploaded file."""

    index: int = Field(description="Position of this form in the file (0-based).")
    status: Literal["ok", "unsupported", "duplicate"] = Field(
        description="ok: extracted. unsupported: not one of the supported forms (pages listed, nothing extracted). "
                    "duplicate: another copy of form `duplicate_of` in this file (e.g. W-2 Copy C).")
    pages: list[int]
    document_type: str = Field(description="Supported form id, or 'unknown'.")
    form_name: str | None = None
    classification: ClassificationResult
    fields: AnyForm | None = None  # type: ignore[valid-type]
    validation: ValidationReport | None = None
    text_layer: bool = Field(description="False when any part of the form was OCR'd.")
    duplicate_of: int | None = None
    extraction_model: str | None = None
    timings_ms: dict[str, int]


class FileResult(BaseModel):
    filename: str
    status: Literal["ok", "failed"]
    error: ErrorBody | None = Field(default=None, description="Why the file could not be read (status failed).")
    document: DocumentInfo | None = None
    forms: list[FormResult] = Field(default_factory=list)


class BulkSummary(BaseModel):
    files: int
    failed_files: int
    forms: int = Field(description="Forms extracted (status ok).")
    unsupported: int
    duplicates: int
    by_type: dict[str, int] = Field(description="Extracted forms per document type.")


class BulkExtractResponse(BaseModel):
    request_id: str
    files: list[FileResult]
    summary: BulkSummary
    timings_ms: dict[str, int]


class DocumentType(BaseModel):
    id: str
    name: str = Field(description="Short form name for display, e.g. W-2, 1099-NEC, K-1 (1065).")
    title: str
    description: str
    json_schema: dict
