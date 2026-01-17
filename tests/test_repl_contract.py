from __future__ import annotations

import pytest

import rlm_corpus_server as server
from corpus_manager import corpus_to_snapshot, create_corpus


@pytest.fixture(autouse=True)
def reset_state():
    server.corpora.clear()
    server.sessions.clear()
    yield
    server.corpora.clear()
    server.sessions.clear()


def _build_sample_documents() -> list[dict[str, str]]:
    text = (
        "Jazz festival crowds gathered in the old harbor.\n"
        "Trumpets and saxophones echoed over the water.\n"
        "Workshops detailed improvisation workflows.\n"
        "Vendors served food as late-night jams unfolded.\n"
    ) * 3
    return [{"document_name": "jazz-notes.txt", "text": text}]


def _snapshot_for_tests():
    corpus = create_corpus(
        name="Test Corpus",
        documents=_build_sample_documents(),
        chunk_size_chars=120,
        chunk_overlap_chars=20,
    )
    return corpus_to_snapshot(corpus)


def _load_corpus_via_tool():
    return server.load_corpus(
        name="Tool Corpus",
        documents=_build_sample_documents(),
        chunk_size_chars=120,
        chunk_overlap_chars=20,
    )


def test_context_contains_expected_chunk_count():
    session = server.REPLSession(_snapshot_for_tests(), context_view="by_chunk")
    result = session.execute("result = len(context)", capture_variables=["result"])
    assert int(result["exports"]["result"]) >= 3


def test_context_meta_alignment_and_filtering():
    session = server.REPLSession(_snapshot_for_tests(), context_view="by_chunk")
    code = """
hits = []
for i, chunk in enumerate(context):
    if "harbor" in chunk.lower():
        hits.append(context_meta[i]["chunk_id"])
"""
    outcome = session.execute(code, capture_variables=["hits"])
    assert "chunk-" in outcome["exports"]["hits"]


def test_llm_query_stub_is_available():
    session = server.REPLSession(_snapshot_for_tests(), context_view="by_chunk")
    outcome = session.execute("answer = llm_query('Explain the schedule')", capture_variables=["answer"])
    assert "[STUB:" in outcome["exports"]["answer"]


def test_exec_repl_persists_state_across_calls():
    corpus_result = _load_corpus_via_tool()
    session_result = server.open_session(corpus_id=corpus_result["corpus_id"], context_view="by_chunk")
    session_id = session_result["session_id"]

    exec_first = server.exec_repl(
        session_id=session_id,
        code="""
hits = []
for i, chunk in enumerate(context):
    if "workshops" in chunk.lower():
        hits.append(context_meta[i]["chunk_id"])
print(f"found {len(hits)} hits")
""",
        capture_variables=["hits"],
    )
    assert "found" in exec_first["stdout"].lower()
    assert "chunk-" in exec_first["exports"]["hits"]

    exec_second = server.exec_repl(
        session_id=session_id,
        code="summary = f'Total hits: {len(hits)}'",
        capture_variables=["summary"],
    )
    assert "Total hits" in exec_second["exports"]["summary"]


def test_close_session_releases_state():
    corpus_result = _load_corpus_via_tool()
    session_result = server.open_session(corpus_id=corpus_result["corpus_id"], context_view="by_chunk")
    session_id = session_result["session_id"]
    assert session_id in server.sessions

    close_result = server.close_session(session_id=session_id)
    assert close_result["closed"] is True
    assert session_id not in server.sessions
