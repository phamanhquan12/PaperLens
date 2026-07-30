"""Unit tests for cleaning filters."""

from __future__ import annotations

from app.ingestion.cleaner import decide_keep_for_text, is_margin_line_number
from collections import Counter


def test_headers_excluded():
    keep, reason = decide_keep_for_text(
        text="ICML 2024",
        label="page_header",
        element_type="TextItem",
        bbox={"l": 100, "t": 700, "r": 200, "b": 690},
        inside_picture=False,
        page_width=612,
        seen_headers=Counter(),
    )
    assert keep is False
    assert reason == "label:page_header"


def test_empty_text_excluded():
    keep, reason = decide_keep_for_text(
        text="",
        label="text",
        element_type="TextItem",
        bbox=None,
        inside_picture=False,
        page_width=612,
        seen_headers=Counter(),
    )
    assert keep is False
    assert reason == "empty_text"


def test_margin_line_numbers_excluded_near_margin():
    assert is_margin_line_number("12", {"l": 6.2, "t": 500, "r": 18, "b": 490}, page_width=612)
    assert not is_margin_line_number(
        "12",
        {"l": 120, "t": 500, "r": 140, "b": 490},
        page_width=612,
    )


def test_body_three_digit_values_retained():
    keep, reason = decide_keep_for_text(
        text="128",
        label="text",
        element_type="TextItem",
        bbox={"l": 120, "t": 400, "r": 150, "b": 390},
        inside_picture=False,
        page_width=612,
        seen_headers=Counter(),
    )
    assert keep is True
    assert reason is None


def test_figure_internal_text_excluded():
    keep, reason = decide_keep_for_text(
        text="accuracy curve",
        label="text",
        element_type="TextItem",
        bbox={"l": 100, "t": 400, "r": 200, "b": 380},
        inside_picture=True,
        page_width=612,
        seen_headers=Counter(),
    )
    assert keep is False
    assert reason == "inside_picture"


def test_section_paths_preserved_in_decision_helpers():
    # Smoke: margin filter uses regex + bbox together
    assert is_margin_line_number("001", {"l": 6, "t": 100, "r": 20, "b": 90}, page_width=612)
    assert not is_margin_line_number("accuracy=001", {"l": 6, "t": 100, "r": 80, "b": 90}, page_width=612)
