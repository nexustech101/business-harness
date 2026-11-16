"""The accuracy evaluator (`tests/evaluate.py`): field comparison and form scoring."""

from __future__ import annotations


def test_evaluator_scores_zero_against_missing_as_an_error():
    from tests.evaluate import compare

    wrong = [r for r in compare({"a": 0.0, "b": None, "c": 5.0}, {"a": None, "b": 0.0, "c": 5}) if not r.ok]
    assert [r.path for r in wrong] == ["a", "b"]
    assert compare({"a": 0.0}, {"a": 0})[0].ok


def test_evaluator_treats_unchecked_and_unread_boxes_alike_but_not_checked():
    from tests.evaluate import compare

    assert compare({"box": False, "rows": []}, {"box": None, "rows": None}) == []
    assert not compare({"box": True}, {"box": None})[0].ok
    assert not compare({"box": False}, {"box": True})[0].ok


def test_score_forms_checks_status_and_missing_fields():
    from tests.evaluate import score_forms

    expected = [{"document_type": "w2", "pages": [1], "fields": {"wages_tips_other_comp": 10.0}},
                {"document_type": "w2", "pages": [2], "status": "duplicate", "fields": {"wages_tips_other_comp": 10.0}}]
    found = [{"document_type": "w2", "pages": [1], "status": "ok", "fields": {"wages_tips_other_comp": 10.0}},
             {"document_type": "w2", "pages": [2], "status": "ok", "fields": None}]
    a, b = score_forms(expected, found)["forms"]
    assert a["identified"] and a["field_accuracy"] == 1.0
    assert not b["identified"] and b["field_accuracy"] == 0.0
