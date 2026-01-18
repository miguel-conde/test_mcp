"""Tests for append_documents tool behavior."""

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


def _seed_corpus() -> str:
    result = server.load_corpus(
        name="Conversation Corpus",
        documents=[{"document_name": "turn-001", "text": "hello world"}],
    )
    return result["corpus_id"]


def test_append_documents_happy_path() -> None:
    corpus_id = _seed_corpus()
    before = server.describe_corpus(corpus_id=corpus_id, include_documents=True)

    result = server.append_documents(
        corpus_id=corpus_id,
        documents=[
            {"document_name": "turn-002", "text": "second turn"},
            {"document_name": "turn-003", "text": "third turn"},
        ],
    )

    assert result["num_documents_before"] == 1
    assert result["num_documents_after"] == 3
    assert result["added"]["num_documents"] == 2

    after = server.describe_corpus(corpus_id=corpus_id, include_documents=True)
    assert after["num_documents"] == 3
    assert after["num_chunks"] > before["num_chunks"]


def test_append_documents_searchable() -> None:
    corpus_id = _seed_corpus()

    server.append_documents(
        corpus_id=corpus_id,
        documents=[{"text": "new content with UNIQUEKEYWORD"}],
    )

    search_result = server.search_corpus(
        corpus_id=corpus_id,
        query="UNIQUEKEYWORD",
    )
    assert search_result["results"], "Expected results for appended content"
    assert "UNIQUEKEYWORD" in search_result["results"][0]["snippet"]


def test_append_documents_chunk_retrievable() -> None:
    corpus_id = _seed_corpus()

    result = server.append_documents(
        corpus_id=corpus_id,
        documents=[{"document_name": "appended", "text": "appended content"}],
    )

    appended_doc_id = result["documents"][0]["document_id"]
    corpus_obj = server.corpora[corpus_id]
    appended_doc = next(
        doc for doc in corpus_obj.documents if doc.document_id == appended_doc_id
    )
    first_chunk_id = appended_doc.chunks[0].chunk_id

    chunk_data = server.get_chunk(corpus_id=corpus_id, chunk_id=first_chunk_id)
    assert chunk_data["document_id"] == appended_doc_id
    assert "appended content" in chunk_data["text"]


def test_append_documents_atomic_validation() -> None:
    corpus_id = _seed_corpus()
    before = server.describe_corpus(corpus_id=corpus_id)

    with pytest.raises(ValueError):
        server.append_documents(
            corpus_id=corpus_id,
            documents=[
                {"text": "valid document"},
                {"text": ""},
                {"text": "another valid"},
            ],
        )

    after = server.describe_corpus(corpus_id=corpus_id)
    assert after["num_documents"] == before["num_documents"]


def test_append_documents_session_snapshot_isolation() -> None:
    corpus_id = _seed_corpus()
    session = server.open_session(
        corpus_id=corpus_id,
        context_view="by_chunk",
    )
    session_id = session["session_id"]

    result1 = server.exec_repl(
        session_id=session_id,
        code="initial_len = len(context)",
        capture_variables=["initial_len"],
    )
    initial_len = int(result1["exports"]["initial_len"])

    server.append_documents(
        corpus_id=corpus_id,
        documents=[{"text": "new content added"}],
    )

    result2 = server.exec_repl(
        session_id=session_id,
        code="current_len = len(context)",
        capture_variables=["current_len"],
    )
    assert int(result2["exports"]["current_len"]) == initial_len

    server.close_session(session_id=session_id)
    new_session = server.open_session(
        corpus_id=corpus_id,
        context_view="by_chunk",
    )

    result3 = server.exec_repl(
        session_id=new_session["session_id"],
        code="new_len = len(context)",
        capture_variables=["new_len"],
    )
    assert int(result3["exports"]["new_len"]) > initial_len
