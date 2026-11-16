"""Extractor helpers: answer cleanup and merging, evidence chunks and token budget. No models."""

from __future__ import annotations

import pytest

from core.forms import ScheduleK1_1065
from core.layout import Block, pair_blocks


def test_clean_separators():
    from core.extractor import clean_separators

    data = {"account_number": "SL-6619024 | 2", "rows": [{"code": "A | B"}], "name": "Plain"}
    flags = clean_separators(data)
    assert data == {"account_number": "SL-6619024", "rows": [{"code": "A"}], "name": "Plain"}
    assert [(f.field, f.code) for f in flags] == [("account_number", "multiple_values"), ("rows[0].code", "multiple_values")]


def test_json_in_text_field_is_flattened():
    from core.extractor import clean_separators

    data = {"distribution_codes": '[{"code": "7", "amount": null}]', "note": "[draft] keep"}
    flags = clean_separators(data)
    assert data == {"distribution_codes": "7", "note": "[draft] keep"}
    assert [(f.field, f.code) for f in flags] == [("distribution_codes", "text_as_json")]


def test_merge_answers_first_value_wins_and_lists_concatenate():
    from core.extractor import merge_answers

    merged = merge_answers([{"payer": {"name": "A", "tin": None}, "rows": [1], "x": None},
                            {"payer": {"name": "B", "tin": "12"}, "rows": [2], "x": "5"}])
    assert merged == {"payer": {"name": "A", "tin": "12"}, "rows": [1, 2], "x": "5"}


def test_chunks_fit_the_token_budget_and_keep_page_markers():
    from core.extractor import LLMExtractor, estimate_tokens

    blocks = [Block(p, 10, 20 + 12 * i, 400, 30 + 12 * i, f"{i} SH FUND {i} 12,345.67 9,876.54 2,469.13")
              for p in (1, 2) for i in range(80)]
    chunks = LLMExtractor.chunks(pair_blocks(blocks, []), budget=400)
    assert len(chunks) > 2
    assert all(estimate_tokens(c) <= 400 for c in chunks)
    assert all(c.startswith("--- page ") for c in chunks)
    joined = "\n".join(chunks)
    assert all(b.text in joined for b in blocks)  # nothing lost


def test_evidence_budget_leaves_room_for_prompt_and_answer():
    from core.config import get_settings
    from core.extractor import ExtractorUnavailable, LLMExtractor

    settings = get_settings().model_copy(update={"extractor_num_ctx": 8192, "extractor_output_tokens": 2048})
    budget = LLMExtractor(settings, client=object()).evidence_budget(ScheduleK1_1065, frozenset())
    assert 0 < budget < (8192 - 2048) * 0.9
    tiny = settings.model_copy(update={"extractor_num_ctx": 2048})
    with pytest.raises(ExtractorUnavailable, match="EXTRACTOR_NUM_CTX"):
        LLMExtractor(tiny, client=object()).evidence_budget(ScheduleK1_1065, frozenset())


def test_estimate_tokens_counts_every_digit():
    from core.extractor import estimate_tokens

    assert estimate_tokens("68,412.55") >= 7
    assert estimate_tokens("Wages, tips, other compensation") <= 11
