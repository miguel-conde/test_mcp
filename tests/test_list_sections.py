"""Tests for list_sections MCP tool."""

from __future__ import annotations

import pytest

import rlm_corpus_server as server


@pytest.fixture(autouse=True)
def reset_state():
    server.corpora.clear()
    server.sessions.clear()
    yield
    server.corpora.clear()
    server.sessions.clear()


def test_list_sections_returns_detected_headings():
    text = """# Introduction
Lorem ipsum dolor sit amet.

## Background
More context here.

### Details
Nested section.
"""
    corpus = server.load_corpus(
        name="Structured Doc",
        documents=[{"document_name": "doc.md", "text": text}],
        chunk_size_chars=100,
        chunk_overlap_chars=0,
    )
    corpus_id = corpus["corpus_id"]

    result = server.list_sections(corpus_id=corpus_id)
    assert len(result["sections"]) >= 3
    assert result["sections"][0]["title"] == "Introduction"
    assert result["sections"][0]["level"] == 1
    assert result["sections"][1]["title"] == "Background"
    assert result["sections"][2]["title"] == "Details"


def test_list_sections_filters_by_document_id():
    corpus = server.load_corpus(
        name="Multi Doc",
        documents=[
            {"document_name": "doc1.md", "text": "# Doc1\nContent"},
            {"document_name": "doc2.md", "text": "# Doc2\nContent"},
        ],
    )
    corpus_id = corpus["corpus_id"]
    corpus_obj = server.corpora[corpus_id]
    first_doc_id = corpus_obj.documents[0].document_id

    result = server.list_sections(corpus_id=corpus_id, document_id=first_doc_id)
    assert all(section["document_id"] == first_doc_id for section in result["sections"])


def test_list_sections_respects_max_level():
    text = """# Level 1
## Level 2
### Level 3
"""
    corpus = server.load_corpus(
        name="Levels",
        documents=[{"text": text}],
    )
    result = server.list_sections(corpus_id=corpus["corpus_id"], max_level=2)
    assert all(section["level"] <= 2 for section in result["sections"])


def test_list_sections_includes_chunk_ids():
    text = """# Section One
""" + ("x" * 5000) + """

## Section Two
""" + ("y" * 5000)

    corpus = server.load_corpus(
        name="Big Doc",
        documents=[{"text": text}],
        chunk_size_chars=3000,
    )
    result = server.list_sections(corpus_id=corpus["corpus_id"])
    # Sections should have chunk_ids
    assert all("chunk_ids" in section for section in result["sections"])
    # At least one section should have multiple chunks
    assert any(len(section["chunk_ids"]) > 1 for section in result["sections"])


def test_list_sections_handles_document_with_no_headings():
    corpus = server.load_corpus(
        name="Plain",
        documents=[{"text": "Just plain text with no markdown headings."}],
    )
    result = server.list_sections(corpus_id=corpus["corpus_id"])
    assert result["sections"] == []
