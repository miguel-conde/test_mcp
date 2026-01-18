from __future__ import annotations

import pytest

import rlm_corpus_server as server


SAMPLE_TEXT = (
    "Fusion energy programs continue to grow and evolve.\n"
    "Researchers study fusion stability and energy capture across labs.\n"
    "Modern labs catalog discoveries about FUSION techniques and safety.\n"
)


@pytest.fixture(autouse=True)
def reset_state() -> None:
    server.corpora.clear()
    server.sessions.clear()
    yield
    server.corpora.clear()
    server.sessions.clear()


def _seed_navigation_corpus() -> str:
    result = server.load_corpus(
        name="Navigation Corpus",
        documents=[
            {"document_name": "overview.txt", "text": SAMPLE_TEXT},
            {"document_name": "labs.txt", "text": SAMPLE_TEXT},
        ],
    )
    return result["corpus_id"]


def test_search_corpus_returns_ranked_hits() -> None:
    corpus_id = _seed_navigation_corpus()
    response = server.search_corpus(corpus_id=corpus_id, query="fusion", top_k=5)
    assert response["results"]
    snippets = [item["snippet"].lower() for item in response["results"]]
    assert any("fusion" in snippet for snippet in snippets)
    scores = [item["score"] for item in response["results"]]
    assert scores == sorted(scores, reverse=True)


def test_get_chunk_returns_payload_and_meta() -> None:
    corpus_id = _seed_navigation_corpus()
    corpus = server.corpora[corpus_id]
    first_document = corpus.documents[0]
    target_chunk = first_document.chunks[0]
    payload = server.get_chunk(corpus_id=corpus_id, chunk_id=target_chunk.chunk_id)
    assert payload["document_id"] == target_chunk.document_id
    assert payload["meta"]["start_offset"] == target_chunk.start_offset
    assert payload["text"]
