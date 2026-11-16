"""Checkbox states from the page image (synthetic pages drawn with OpenCV). No models."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from core.checkboxes import checkbox_states, find_squares
from core.extractor import checkbox_labels
from core.forms import W2, Form1098T
from core.layout import Block

BOX = 13  # ~8 pt in block units; the test page is 1000 px wide, so 1 px = 1 unit


def _page():
    return np.full((1300, 1000), 255, np.uint8)


def _box(img, x, y, mark=None):
    cv2.rectangle(img, (x, y), (x + BOX, y + BOX), 0, 1)
    if mark == "x":  # vector X, no text
        cv2.line(img, (x + 3, y + 3), (x + BOX - 3, y + BOX - 3), 0, 2)
        cv2.line(img, (x + BOX - 3, y + 3), (x + 3, y + BOX - 3), 0, 2)
    elif mark == "tick":
        cv2.line(img, (x + 3, y + 7), (x + 6, y + BOX - 3), 0, 2)
        cv2.line(img, (x + 6, y + BOX - 3), (x + BOX - 2, y + 3), 0, 2)
    elif mark == "fill":
        cv2.rectangle(img, (x, y), (x + BOX, y + BOX), 0, -1)


def test_checkboxes_box_left_of_label_with_vector_x():
    img = _page()
    _box(img, 80, 100, "x")
    _box(img, 280, 100)
    blocks = [Block(1, 98, 100, 200, 112, "13 Retirement plan"), Block(1, 298, 100, 420, 112, "13 Third-party sick pay")]
    states = checkbox_states(blocks, checkbox_labels(W2), lambda page: img)
    assert states == {"retirement_plan": True, "third_party_sick_pay": False}


def test_checkboxes_below_labels_like_a_real_w2():
    img = _page()
    for x, mark in ((60, None), (210, "tick"), (360, None)):
        _box(img, x + 40, 130, mark)
    blocks = [Block(1, 60, 100, 160, 110, "Statutory employee"), Block(1, 210, 100, 300, 110, "Retirement plan"),
              Block(1, 360, 100, 470, 110, "Third-party sick pay")]
    states = checkbox_states(blocks, checkbox_labels(W2), lambda page: img)
    assert states == {"statutory_employee": False, "retirement_plan": True, "third_party_sick_pay": False}


def test_checkboxes_right_of_label_and_inline_mark_like_a_1098t():
    img = _page()
    _box(img, 905, 330, "fill")  # box 8: square at the right end of the line
    _box(img, 505, 380)  # box 9: square at the start of the line, text layer ran the label over it
    blocks = [Block(1, 732, 330, 890, 344, "8 Check if at least half-time student"),
              Block(1, 507, 380, 690, 394, "X 9 Checked if a graduate student")]
    states = checkbox_states(blocks, checkbox_labels(Form1098T), lambda page: img)
    assert states == {"at_least_half_time_student": True, "graduate_student": False}


def test_checkboxes_ignore_ocr_misreads():
    """OCR text says '冈' (ticked) and 'X' (empty box); the pixels decide."""
    img = _page()
    _box(img, 50, 445, "x")
    _box(img, 280, 448)
    blocks = [Block(1, 54, 446, 74, 464, "冈"), Block(1, 74, 445, 160, 458, "13 Retirement plan"),
              Block(1, 281, 448, 294, 459, "X"), Block(1, 296, 442, 400, 458, "13 Third-party sick pay")]
    states = checkbox_states(blocks, checkbox_labels(W2), lambda page: img)
    assert states == {"retirement_plan": True, "third_party_sick_pay": False}


def test_checkboxes_missing_label_or_box_is_left_to_the_model():
    img = _page()
    blocks = [Block(1, 98, 100, 200, 112, "13 Retirement plan")]  # no square printed anywhere
    assert checkbox_states(blocks, checkbox_labels(W2), lambda page: img) == {}
    assert checkbox_states([], checkbox_labels(W2), lambda page: img) == {}


def test_square_finder_rejects_letters():
    img = _page()
    # Printed-size glyphs (~9 pt at 150 DPI): round or open shapes fail the edge/corner tests.
    cv2.putText(img, "O D 0 B Q", (100, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 1)
    cv2.putText(img, "O D 0 B Q", (100, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
    _box(img, 400, 185)
    squares = find_squares(img, page=1)
    assert len(squares) == 1 and squares[0].left == pytest.approx(400, abs=1)
