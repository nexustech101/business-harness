"""layout.py

Text of a converted document as positioned blocks, and those blocks as visual lines.

Docling's reading order works for prose but scatters the cells of forms, invoices and tables. This module keeps
each text line's bounding box instead (page-scaled: a page is 1000 units wide, origin top left), so
`lines_of` can rebuild the lines a reader sees: top to bottom, left to right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise

from docling.datamodel.document import ConversionResult
from docling_core.types.doc import DoclingDocument, TableItem, TextItem

SCALE = 1000.0  # coordinates are normalised to 0..1000 of page width
LINE_TOLERANCE = 0.5  # share of a line's height two blocks may differ in top and still share a line


@dataclass
class Block:
    page: int
    left: float
    top: float
    right: float
    bottom: float
    text: str
    ocr: bool = False  # read by OCR (scan/photo region) rather than a PDF text layer


def blocks_from_conversion(result: ConversionResult) -> list[Block]:
    """
    Line-level text blocks with page-scaled, top-left-origin boxes.

    Uses the raw page cells (PDF text lines or OCR lines) rather than the
    layout model's clusters, which sometimes merge neighbouring boxes. PDF
    text lines are re-split on wide horizontal gaps using the word cells,
    because docling-parse joins everything that shares a baseline.
    Requires ``generate_parsed_pages=True``; otherwise falls back to the
    document's items.
    """
    blocks: list[Block] = []
    for page in result.pages:
        if page.size is None or not page.cells:
            continue
        k = SCALE / page.size.width
        words = page.parsed_page.word_cells if page.parsed_page is not None else []
        for cell in page.cells:
            box = cell.rect.to_bounding_box().to_top_left_origin(page.size.height)
            pieces = [] if cell.from_ocr else _split_on_gaps(box, words, page.size.height)
            for left, top, right, bottom, text in pieces or [(box.l, box.t, box.r, box.b, cell.text)]:
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    blocks.append(Block(page.page_no, left * k, top * k, right * k, bottom * k, text,
                                        ocr=bool(cell.from_ocr)))
    if not blocks:
        return blocks_from_document(result.document)
    blocks.sort(key=lambda b: (b.page, round(b.top / 4), b.left))
    return blocks


def _split_on_gaps(line_box, words, page_height: float) -> list[tuple[float, float, float, float, str]]:
    """Regroup the words inside a PDF text line into runs separated by wide gaps."""
    inside = []
    for w in words:
        wb = w.rect.to_bounding_box().to_top_left_origin(page_height)
        cx, cy = (wb.l + wb.r) / 2, (wb.t + wb.b) / 2
        if line_box.l - 1 <= cx <= line_box.r + 1 and line_box.t - 1 <= cy <= line_box.b + 1:
            inside.append((wb, w.text))
    if len(inside) < 2:
        return []
    inside.sort(key=lambda x: x[0].l)
    height = max(line_box.b - line_box.t, 1.0)
    runs, current = [], [inside[0]]
    for prev, cur in pairwise(inside):
        if cur[0].l - prev[0].r > max(height, 4.0):  # word spacing is ~0.3x height
            runs.append(current)
            current = []
        current.append(cur)
    runs.append(current)
    if len(runs) == 1:
        return []
    return [
        (run[0][0].l, min(w.t for w, _ in run), run[-1][0].r, max(w.b for w, _ in run), " ".join(t for _, t in run))
        for run in runs
    ]


def blocks_from_document(doc: DoclingDocument) -> list[Block]:
    """Fallback: every text item / table cell of the converted document."""
    blocks: list[Block] = []

    def add(page_no: int, bbox, text: str) -> None:
        text = re.sub(r"\s+", " ", text or "").strip()
        page = doc.pages.get(page_no)
        if not text or page is None or page.size is None:
            return
        b = bbox.to_top_left_origin(page.size.height)
        k = SCALE / page.size.width
        blocks.append(Block(page_no, b.l * k, b.t * k, b.r * k, b.b * k, text))

    for item, _level in doc.iterate_items():
        if isinstance(item, TableItem) and item.prov:
            for cell in item.data.table_cells:
                if cell.bbox is not None:
                    add(item.prov[0].page_no, cell.bbox, cell.text)
        elif isinstance(item, TextItem) and item.prov:
            add(item.prov[0].page_no, item.prov[0].bbox, item.text)

    blocks.sort(key=lambda b: (b.page, round(b.top / 4), b.left))
    return blocks


def lines_of(blocks: list[Block]) -> list[list[Block]]:
    """Group blocks into visual lines (per page, top to bottom, left to right)."""
    lines: list[list[Block]] = []
    for b in sorted(blocks, key=lambda b: (b.page, b.top, b.left)):
        if lines:
            last = lines[-1]
            ref = last[0]
            height = max(ref.bottom - ref.top, b.bottom - b.top, 4.0)
            if ref.page == b.page and abs(b.top - ref.top) <= LINE_TOLERANCE * height:
                last.append(b)
                continue
        lines.append([b])
    return [sorted(line, key=lambda b: b.left) for line in lines]
