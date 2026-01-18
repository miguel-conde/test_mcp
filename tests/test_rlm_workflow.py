from rlm_corpus_server import load_corpus, open_session, exec_repl, close_session


SAMPLE_PAPER_TEXT = (
    """
    This is a sample research paper text used for testing.\n\n
    Methods and methodology are discussed throughout this document.\n
    In the Methods section we describe the experimental setup. The method includes dataset preparation, model architecture, and evaluation.\n
    Results show improvements. The discussion references the method and methods used.\n
    Conclusion: the proposed method outperforms baselines.\n
    """ * 20
)


def test_paper_faithful_workflow():
    # 1. Load corpus
    corpus = load_corpus(
        name="Research Papers",
        documents=[{
            "document_name": "paper1.txt",
            "text": SAMPLE_PAPER_TEXT
        }]
    )

    # 2. Open session with by_chunk view
    session = open_session(
        corpus_id=corpus["corpus_id"],
        context_view="by_chunk",
        enable_llm_query=False
    )

    # 3. Execute filtering code (regex + aggregation)
    exec_result1 = exec_repl(
        session_id=session["session_id"],
        code="""
import re

# Filter chunks with 'method' mentions
method_chunks = []
for i, chunk in enumerate(context):
    if re.search(r'\\bmethod(s)?\\b', chunk, re.IGNORECASE):
        method_chunks.append({
            'chunk_id': context_meta[i]['chunk_id'],
            'document_id': context_meta[i]['document_id'],
            'text': chunk[:200]
        })

print(f"Found {len(method_chunks)} method chunks")
        """,
        capture_variables=["method_chunks"]
    )

    assert "Found" in exec_result1["stdout"]
    assert len(exec_result1["exports"]["method_chunks"]) > 0

    # 4. Second execution: call llm_query (stub) on aggregated chunks
    exec_result2 = exec_repl(
        session_id=session["session_id"],
        code="""
# Aggregate preview texts
aggregated = "\\n---\\n".join([c['text'] for c in method_chunks])

# Call llm_query (stub)
summary = llm_query(f"Summarize these method descriptions: {aggregated}")

final_answer = f"Methods summary: {summary}"
        """,
        capture_variables=["final_answer", "summary"]
    )

    assert "STUB" in exec_result2["exports"]["summary"]
    assert "final_answer" in exec_result2["exports"]

    # 5. Close session
    close_result = close_session(session_id=session["session_id"])
    assert close_result["closed"] == True
