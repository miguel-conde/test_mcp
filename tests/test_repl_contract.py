from __future__ import annotations

from typing import Any, Dict, List

from rlm_corpus_server import REPLSession


def _build_snapshot() -> Dict[str, Any]:
    chunk_specs = [
        ("chunk-000001", "Jazz festival lineups draw global talent."),
        ("chunk-000002", "Workshops explain improvisation workflows and reharmonization."),
        ("chunk-000003", "Late night jam sessions revisit festival highlights."),
    ]

    chunks = []
    for index, (chunk_id, text) in enumerate(chunk_specs):
        start = index * 120
        chunks.append(
            {
                "chunk_id": chunk_id,
                "document_id": "doc-000001",
                "text": text,
                "start_offset": start,
                "end_offset": start + len(text),
                "section_id": None,
                "meta": {"index": index, "estimated_tokens": max(1, len(text) // 4)},
            }
        )

    documents = [
        {
            "document_id": "doc-000001",
            "document_name": "jazz-notes.txt",
            "text": " ".join(text for _, text in chunk_specs),
            "chunks": chunks,
        }
    ]
    return {"corpus_id": "corpus-test", "documents": documents}


def test_context_contains_expected_chunk_count():
    session = REPLSession(_build_snapshot(), context_view="by_chunk")
    result = session.execute("result = len(context)", capture_variables=["result"])
    assert result["exports"]["result"] == "3"


def test_context_meta_alignment_and_filtering():
    session = REPLSession(_build_snapshot(), context_view="by_chunk")
    code = """
hits = []
for i, chunk in enumerate(context):
    if "festival" in chunk.lower():
        hits.append(context_meta[i]["chunk_id"])
"""
    outcome = session.execute(code, capture_variables=["hits"])
    assert "chunk-000001" in outcome["exports"]["hits"]


def test_llm_query_stub_is_available():
    session = REPLSession(_build_snapshot(), context_view="by_chunk")
    outcome = session.execute("answer = llm_query('Explain the schedule')", capture_variables=["answer"])
    assert "[STUB:" in outcome["exports"]["answer"]
