"""Upload sniffing, classifier input, the heading classifier and splitting a file into forms. No models."""

from __future__ import annotations

import pytest

from core.forms import FORMS
from core.layout import Block
from core.parser import ParsedDocument, UnsupportedDocument, sniff
from core.segment import split
from core.tev import NONE_OPTION, build_state, criteria


def test_sniff_uses_magic_bytes():
    assert sniff(b"%PDF-1.7 ...")[0] == "application/pdf"
    assert sniff(b"\x89PNG\r\n\x1a\n....")[0] == "image/png"
    assert sniff(b"\xff\xd8\xff\xe0...")[0] == "image/jpeg"
    with pytest.raises(UnsupportedDocument):
        sniff(b"PK\x03\x04 a zip file")


def test_build_state_puts_form_titles_first_and_caps_length():
    text = "lots of noise\n" * 500 + "Form 1099-INT Interest Income\n"
    state = build_state(text, 300)
    assert state.startswith("Form 1099-INT Interest Income")
    assert len(state) <= 300


def test_criteria_cover_all_forms_and_none():
    assert set(criteria()) == set(FORMS) | {NONE_OPTION}


def test_heading_classifier_needs_no_model():
    import asyncio

    from core.tev import HeadingClassifier

    c = asyncio.run(HeadingClassifier().classify("PAYER'S TIN 12-3456789\n2025 Form 1099-INT Interest Income\n1 Interest income 5.00"))
    assert (c.document_type, c.model) == ("1099_int", "headings")
    assert asyncio.run(HeadingClassifier().classify("INVOICE #10442\nTotal due $949.50")).document_type == "unknown"


def _doc(blocks, pages):
    return ParsedDocument("f.pdf", "application/pdf", "0" * 64, pages, True, blocks,
                          {p: 1294.0 for p in range(1, pages + 1)}, 0)


def test_split_stack_of_forms_one_per_page():
    blocks = [Block(1, 30, 30, 200, 45, "Form W-2"), Block(1, 30, 100, 200, 110, "1 Wages 1,000.00"),
              Block(2, 30, 30, 200, 45, "Form 1099-NEC"), Block(2, 30, 100, 200, 110, "1 Nonemployee 500.00"),
              Block(3, 30, 100, 200, 110, "Instructions for Recipient ... instead of Form W-2 because"),
              Block(4, 30, 30, 200, 45, "Form 1098-T")]
    segments = split(_doc(blocks, 4))
    # The instructions page has no heading and follows a single-page form: its own (unidentified) segment.
    assert [(s.form_hint, s.pages) for s in segments] == [("w2", [1]), ("1099_nec", [2]), (None, [3]), ("1098_t", [4])]


def test_split_consolidated_statement_into_sections_with_shared_header():
    blocks = [Block(1, 30, 20, 400, 35, "2025 TAX REPORTING STATEMENT  Account 5521-0098"),
              Block(1, 30, 40, 400, 55, "PAYER'S TIN 41-1228890  RECIPIENT'S TIN XXX-XX-4417"),
              Block(1, 30, 100, 500, 115, "2025 Form 1099-DIV Dividends and Distributions"),
              Block(1, 30, 120, 300, 130, "1a Total ordinary dividends 812.40"),
              Block(1, 30, 300, 500, 315, "2025 Form 1099-INT Interest Income"),
              Block(1, 30, 320, 300, 330, "1 Interest income 96.12"),
              Block(2, 30, 20, 600, 35, "Form 1099-B Proceeds From Broker and Barter Exchange Transactions"),
              Block(2, 30, 60, 300, 70, "100 SH APPLE INC 19,450.00"),
              Block(3, 30, 20, 600, 35, "Form 1099-B (continued) Proceeds From Broker"),
              Block(3, 30, 60, 300, 70, "50 SH MSFT 2,900.00")]
    segments = split(_doc(blocks, 3))
    assert [(s.form_hint, s.pages) for s in segments] == [("1099_div", [1]), ("1099_int", [1]), ("1099_b", [2, 3])]
    assert all("PAYER'S TIN 41-1228890" in s.text for s in segments)
    assert "Interest income" not in "\n".join(b.text for b in segments[0].blocks)


def test_split_copies_of_one_form_on_a_page_stay_one_form():
    blocks = [Block(1, 30, 30, 200, 45, "Form W-2"), Block(1, 30, 640, 200, 655, "Form W-2"),
              Block(1, 30, 100, 200, 110, "1 Wages 1,000.00"), Block(1, 30, 700, 200, 710, "1 Wages 1,000.00")]
    assert [(s.form_hint, s.pages) for s in split(_doc(blocks, 1))] == [("w2", [1])]


def test_split_reads_ocr_glued_and_split_headings_and_footers():
    blocks = [Block(1, 40, 50, 115, 60, "Form"), Block(1, 97, 52, 194, 62, "n 1098-E"),
              Block(2, 43, 63, 401, 75, "Form 1099-MISCMiscellaneous Information"),
              Block(3, 47, 50, 459, 62, "Form SSA-109 Social Security Beft Statement"),
              Block(3, 47, 1246, 430, 1258, "Form SSA-1099 Social Security Benefit Statement (keep for your records)www.irs.gov"),
              Block(4, 56, 287, 432, 299, "2025 Form1099-DIV Dividends and Distributions")]
    assert [(s.form_hint, s.pages) for s in split(_doc(blocks, 4))] == [
        ("1098_e", [1]), ("1099_misc", [2]), ("ssa_1099", [3]), ("1099_div", [4])]


def test_split_without_headings_is_one_unlabelled_form():
    blocks = [Block(1, 30, 100, 200, 110, "Wages 1,000.00"), Block(2, 30, 100, 200, 110, "more")]
    assert [(s.form_hint, s.pages) for s in split(_doc(blocks, 2))] == [(None, [1, 2])]
