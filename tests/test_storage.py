from __future__ import annotations

from pathlib import Path

from corpus_manager import create_corpus
from storage import SQLiteStorage


def _build_sample_corpus():
    return create_corpus(
        name="Sample",
        documents=[{"document_name": "doc.txt", "text": "Alpha beta gamma delta."}],
        chunk_size_chars=16,
        chunk_overlap_chars=0,
    )


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "corpora.db"
    storage = SQLiteStorage(db_path=str(db_path))
    corpus = _build_sample_corpus()

    storage.save_corpus(corpus)
    restored = storage.load_corpus(corpus.corpus_id)

    assert restored is not None
    assert restored.corpus_id == corpus.corpus_id
    assert len(restored.documents) == 1
    assert restored.documents[0].chunks


def test_list_and_delete(tmp_path: Path) -> None:
    storage = SQLiteStorage(db_path=str(tmp_path / "store.db"))
    corpus = _build_sample_corpus()
    storage.save_corpus(corpus)

    summaries = storage.list_corpora()
    assert any(item["corpus_id"] == corpus.corpus_id for item in summaries)

    assert storage.delete_corpus(corpus.corpus_id) is True
    assert storage.load_corpus(corpus.corpus_id) is None
