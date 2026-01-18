"""Tests for section_detector module."""

from __future__ import annotations

import pytest

from section_detector import detect_sections


def test_detect_sections_finds_markdown_headings():
    text = """# Introduction
Some intro text here.

## Background
More details about background.

### Subsection
Nested content.
"""
    sections = detect_sections(text)
    assert len(sections) >= 3
    assert sections[0]["title"] == "Introduction"
    assert sections[0]["level"] == 1
    assert sections[1]["title"] == "Background"
    assert sections[1]["level"] == 2
    assert sections[2]["title"] == "Subsection"
    assert sections[2]["level"] == 3


def test_detect_sections_respects_max_level():
    text = """# Level 1
## Level 2
### Level 3
#### Level 4
"""
    sections = detect_sections(text, max_level=2)
    assert len(sections) == 2
    assert sections[0]["level"] == 1
    assert sections[1]["level"] == 2


def test_detect_sections_calculates_end_offsets():
    text = """# First
Content for first.

## Second
Content for second.
"""
    sections = detect_sections(text)
    assert sections[0]["end_offset"] == sections[1]["start_offset"]
    assert sections[1]["end_offset"] == len(text)


def test_detect_sections_rejects_invalid_max_level():
    with pytest.raises(ValueError, match="max_level must be positive"):
        detect_sections("# Test", max_level=0)


def test_detect_sections_handles_no_headings():
    text = "Just plain text with no headings."
    sections = detect_sections(text)
    assert sections == []
