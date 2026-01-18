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


def _load_small_corpora(count: int = 2) -> list[str]:
    corpus_ids: list[str] = []
    for idx in range(count):
        result = server.load_corpus(
            name=f"Corpus {idx}",
            documents=[{"document_name": "doc.txt", "text": f"alpha beta {idx}"}],
        )
        corpus_ids.append(result["corpus_id"])
    return corpus_ids


def test_list_corpus_returns_metadata() -> None:
    _load_small_corpora(3)
    response = server.list_corpus()
    assert len(response["corpora"]) == 3
    assert {item["name"] for item in response["corpora"]} == {"Corpus 0", "Corpus 1", "Corpus 2"}


def test_describe_corpus_optionally_includes_documents_and_chunks() -> None:
    corpus_id = _load_small_corpora(1)[0]
    payload = server.describe_corpus(
        corpus_id=corpus_id,
        include_documents=True,
        include_chunks=True,
    )
    assert payload["num_documents"] == 1
    assert payload["documents"][0]["chunks"], "Expected chunk metadata"


def test_delete_corpus_requires_force_when_sessions_active() -> None:
    corpus_id = _load_small_corpora(1)[0]
    session = server.open_session(corpus_id=corpus_id)
    with pytest.raises(ValueError):
        server.delete_corpus(corpus_id)
    result = server.delete_corpus(corpus_id, force=True)
    assert result["deleted"] is True
    assert session["session_id"] not in server.sessions
