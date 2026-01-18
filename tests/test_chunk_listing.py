from __future__ import annotations

import pytest

import rlm_corpus_server as server


@pytest.fixture(autouse=True)
def reset_state() -> None:
    server.corpora.clear()
    server.sessions.clear()
    yield
    server.corpora.clear()
    server.sessions.clear()


def test_list_chunks_limits_and_filters_results() -> None:
    corpus = server.load_corpus(
        name="Chunk Index",
        documents=[
            {"document_name": "one.txt", "text": "alpha beta gamma delta"},
            {"document_name": "two.txt", "text": "epsilon zeta eta theta"},
        ],
        chunk_size_chars=12,
        chunk_overlap_chars=0,
    )
    corpus_id = corpus["corpus_id"]
    first_document_id = server.corpora[corpus_id].documents[0].document_id

    limited = server.list_chunks(corpus_id=corpus_id, limit=1)
    assert limited["total_returned"] == 1

    filtered = server.list_chunks(
        corpus_id=corpus_id,
        document_id=first_document_id,
        include_text=True,
    )
    assert all(item["document_id"] == first_document_id for item in filtered["chunks"])
    assert "text" in filtered["chunks"][0]
