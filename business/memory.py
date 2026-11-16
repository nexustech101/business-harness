"""business/memory.py

Workspace memory: what the workspace knows about the business, kept in the same vector index as the uploaded
files, so a search (and the knowledge map) covers both. Three records per owner, each a Markdown document in the
library whose `location` starts with `workspace://` (`library.schema.WORKSPACE_PREFIX`):

| Location                | Title              | Sections                                                    |
|-------------------------|--------------------|-------------------------------------------------------------|
| `workspace://profile`   | Business profile   | one per profile section; one per department and per role    |
| `workspace://discovery` | Discovery answers  | one per interview area: each question with the owner's answer |
| `workspace://notes`     | Shared notes       | one per notes-board topic (the newest `MAX_NOTES` notes)    |

`sync` renders the records and replaces the stored ones whose text changed (compared by content hash, so an
unchanged workspace costs three lookups and no embedding call). It runs before anything searches: the knowledge
routes, the partner, assistant runs and the document assistant. The context layers of business/context.py are
cut to a budget; these records are not, which is why nothing of a large profile is out of an assistant's reach.

*Usage:*
>>> await sync(business, owner)                  # idempotent
>>> [r.location for r in records(profile, answers, notes)]
['workspace://profile', 'workspace://discovery', 'workspace://notes']
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from business.questions import AREA_LABELS, QUESTIONS
from business.schema import Answer, BusinessProfile, Note
from core.utils import mask_ssns
from library.ingest import DocumentDraft, markdown_chunks
from library.schema import WORKSPACE_PREFIX, FileType

if TYPE_CHECKING:
    from business.service import Business
    from library.service import Library

MAX_NOTES = 500
PROFILE, DISCOVERY, NOTES = (WORKSPACE_PREFIX + name for name in ("profile", "discovery", "notes"))


@dataclass
class Record:
    location: str
    title: str
    markdown: str  # "" when there is nothing to remember: the stored record is removed


# --- Rendering -----------------------------------------------------------------------------------------


def _section(title: str, lines: list[str]) -> list[str]:
    lines = [line for line in lines if line.strip()]
    return [f"## {title}", *lines, ""] if lines else []


def _bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items if item]


def _labelled(label: str, value: object) -> str:
    value = "; ".join(map(str, value)) if isinstance(value, list) else value
    return f"{label}: {value}" if value not in (None, "", []) else ""


def profile_markdown(profile: BusinessProfile) -> str:
    """The whole profile, one section per topic and one per department and role (nothing is cut)."""
    p, f = profile, profile.financials
    lines = [
        *_section("Overview", [_labelled("Business", p.name), p.summary, _labelled("Industry", p.industry),
                               _labelled("Business model", p.business_model), _labelled("Stage", p.stage),
                               _labelled("Team size", p.team_size), _labelled("Locations", p.locations)]),
        *_section("Products and services", _bullets(p.offerings)),
        *_section("Customers", [p.customers]),
        *_section("Goals", _bullets(p.goals)),
        *_section("Pain points", _bullets(p.pain_points)),
    ]
    for d in p.departments:
        lines += _section(f"Department: {d.name}", [d.purpose, _labelled("Led by", d.head),
                                                    *_bullets(d.responsibilities)])
    for r in p.roles:
        lines += _section(f"Role: {r.title}", [_labelled("Department", r.department), _labelled("Held by", r.people),
                                               _labelled("Reports to", r.reports_to), _labelled("Tools", r.tools),
                                               *_bullets(r.duties)])
    lines += _section("Tools and systems", [
        f"- {t.name}" + (f" ({t.category})" if t.category else "") + (f": {t.used_for}" if t.used_for else "")
        + (f" | used by {', '.join(t.departments)}" if t.departments else "") for t in p.tools])
    lines += _section("Information flows", [
        f"- {fl.what}: {fl.source} -> {fl.target}" + (f", {fl.cadence}" if fl.cadence else "")
        + (f", via {fl.via}" if fl.via else "") for fl in p.flows])
    lines += _section("Finance", [
        _labelled("Revenue streams", f.revenue_streams), _labelled("Cost centers", f.cost_centers),
        _labelled("Pricing", f.pricing), _labelled("Accounting method", f.accounting_method),
        _labelled("Fiscal year end", f.fiscal_year_end), _labelled("Reports", f.reporting),
        _labelled("Currency", f.currency) if any((f.revenue_streams, f.cost_centers, f.pricing)) else ""])
    lines += _section("Compliance", _bullets(p.compliance))
    return "\n".join(lines).strip()


def discovery_markdown(answers: dict[str, Answer]) -> str:
    """The owner's interview answers by area, each under its question."""
    by_area: dict[str, list[str]] = {}
    for question_id, answer in answers.items():
        question = QUESTIONS.get(question_id)
        if question is not None:
            by_area.setdefault(question.area, []).extend([f"Q: {question.text}", f"A: {answer.answer}", ""])
    lines = [line for area, label in AREA_LABELS.items() for line in _section(label, by_area.get(area, []))]
    return "\n".join(lines).strip()


def notes_markdown(notes: list[Note]) -> str:
    """The notes board by topic, newest first inside each topic."""
    by_topic: dict[str, list[str]] = {}
    for note in notes:
        by_topic.setdefault(note.topic.lower(), []).append(
            f"- {note.author}, {note.created_at:%Y-%m-%d %H:%M}: {note.text}")
    return "\n".join(line for topic in sorted(by_topic) for line in _section(topic, by_topic[topic])).strip()


def records(profile: BusinessProfile, answers: dict[str, Answer], notes: list[Note]) -> list[Record]:
    return [Record(PROFILE, "Business profile", profile_markdown(profile)),
            Record(DISCOVERY, "Discovery answers", discovery_markdown(answers)),
            Record(NOTES, "Shared notes", notes_markdown(notes))]


def draft(record: Record, chunk_chars: int) -> DocumentDraft:
    """The record as a library document (Markdown, one or more chunks per section, SSNs masked)."""
    data = record.markdown.encode()
    chunks = markdown_chunks(record.markdown, chunk_chars)
    for chunk in chunks:
        chunk.content = mask_ssns(chunk.content)
    return DocumentDraft(title=record.title, type=FileType.MD, media_type="text/markdown", length_bytes=len(data),
                         location=record.location, content_hash=hashlib.sha256(data).hexdigest(), chunks=chunks)


# --- Sync ----------------------------------------------------------------------------------------------


async def sync(business: Business, owner: str) -> int:
    """Bring the owner's records in the index up to date; returns how many were written or removed. One sync
    per owner at a time (`Business.memory_lock`)."""
    async with business.memory_lock(owner):
        library = business.library

        def gather() -> list[tuple[Record, list[tuple[str, str]]]]:
            current = records(business.profile(owner), business.store.answers(owner),
                              business.store.notes(owner, None, MAX_NOTES))
            return [(record, library.at_location(owner, record.location)) for record in current]

        changes = [await _refresh(library, owner, record, stored)
                   for record, stored in await asyncio.to_thread(gather)]
        return sum(changes)


async def _refresh(library: Library, owner: str, record: Record, stored: list[tuple[str, str]]) -> bool:
    """Make the index hold exactly `record`'s current text; `stored`: (document id, content hash) of what it
    holds for that record now. True when something was written or removed."""
    fresh = draft(record, library.config.chunk_chars) if record.markdown else None
    if fresh is not None and not fresh.chunks:
        fresh = None
    current = fresh.content_hash if fresh else None
    stale = [document_id for document_id, content_hash in stored if content_hash != current]
    missing = fresh is not None and len(stale) == len(stored)
    if missing:  # added before the old record goes: an embedding outage leaves the old one searchable
        await library.add(fresh, owner, record.markdown.encode())
    for document_id in stale:
        await asyncio.to_thread(library.delete, document_id, owner)
    return missing or bool(stale)
