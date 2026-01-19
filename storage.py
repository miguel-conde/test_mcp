from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from corpus_manager import Chunk, Corpus, Document


class StorageBackend(ABC):
    @abstractmethod
    def save_corpus(self, corpus: Corpus) -> None:
        pass

    @abstractmethod
    def load_corpus(self, corpus_id: str) -> Optional[Corpus]:
        pass

    @abstractmethod
    def delete_corpus(self, corpus_id: str) -> bool:
        pass

    @abstractmethod
    def list_corpora(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_chunk(self, corpus_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
        pass


class SQLiteStorage(StorageBackend):
    def __init__(self, db_path: str = "rlm_corpus.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def save_corpus(self, corpus: Corpus) -> None:
        with self._connection() as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM corpora WHERE corpus_id = ?", (corpus.corpus_id,))
            conn.execute(
                """
                INSERT INTO corpora (corpus_id, name, created_at, chunk_size_chars, chunk_overlap_chars, meta)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    corpus.corpus_id,
                    corpus.name,
                    corpus.created_at.isoformat(),
                    corpus.chunk_size_chars,
                    corpus.chunk_overlap_chars,
                    json.dumps(corpus.meta or {}, ensure_ascii=False),
                ),
            )
            conn.execute("DELETE FROM documents WHERE corpus_id = ?", (corpus.corpus_id,))
            conn.execute("DELETE FROM chunks WHERE corpus_id = ?", (corpus.corpus_id,))
            for document in corpus.documents:
                conn.execute(
                    """
                    INSERT INTO documents (
                        document_id,
                        corpus_id,
                        document_name,
                        text,
                        sections,
                        meta
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.document_id,
                        corpus.corpus_id,
                        document.document_name,
                        document.text,
                        json.dumps(document.sections or [], ensure_ascii=False),
                        json.dumps(document.meta or {}, ensure_ascii=False),
                    ),
                )
                for chunk in document.chunks:
                    conn.execute(
                        """
                        INSERT INTO chunks (
                            chunk_id,
                            corpus_id,
                            document_id,
                            section_id,
                            start_offset,
                            end_offset,
                            text,
                            meta
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk.chunk_id,
                            corpus.corpus_id,
                            document.document_id,
                            chunk.section_id,
                            chunk.start_offset,
                            chunk.end_offset,
                            chunk.text,
                            json.dumps(chunk.meta or {}, ensure_ascii=False),
                        ),
                    )

    def load_corpus(self, corpus_id: str) -> Optional[Corpus]:
        with self._connection() as conn:
            corpus_row = conn.execute(
                "SELECT * FROM corpora WHERE corpus_id = ?",
                (corpus_id,),
            ).fetchone()
            if not corpus_row:
                return None
            doc_rows = conn.execute(
                "SELECT * FROM documents WHERE corpus_id = ? ORDER BY rowid",
                (corpus_id,),
            ).fetchall()
            chunk_rows = conn.execute(
                "SELECT * FROM chunks WHERE corpus_id = ? ORDER BY rowid",
                (corpus_id,),
            ).fetchall()

        chunks_by_document: Dict[str, List[Chunk]] = {}
        for row in chunk_rows:
            chunk = Chunk(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                text=row["text"],
                start_offset=row["start_offset"],
                end_offset=row["end_offset"],
                meta=json.loads(row["meta"] or "{}"),
                section_id=row["section_id"],
            )
            chunks_by_document.setdefault(chunk.document_id, []).append(chunk)

        documents: List[Document] = []
        for row in doc_rows:
            sections = json.loads(row["sections"] or "[]")
            doc = Document(
                document_id=row["document_id"],
                document_name=row["document_name"],
                text=row["text"],
                sections=sections,
            )
            doc.meta = json.loads(row["meta"] or "{}")
            doc.chunks = chunks_by_document.get(doc.document_id, [])
            doc.meta["num_chunks"] = len(doc.chunks)
            documents.append(doc)

        return Corpus(
            corpus_id=corpus_row["corpus_id"],
            name=corpus_row["name"],
            created_at=datetime.fromisoformat(corpus_row["created_at"]),
            documents=documents,
            chunk_size_chars=corpus_row["chunk_size_chars"],
            chunk_overlap_chars=corpus_row["chunk_overlap_chars"],
            meta=json.loads(corpus_row["meta"] or "{}"),
        )

    def delete_corpus(self, corpus_id: str) -> bool:
        with self._connection() as conn:
            deleted = conn.execute(
                "DELETE FROM corpora WHERE corpus_id = ?",
                (corpus_id,),
            ).rowcount
            conn.execute("DELETE FROM documents WHERE corpus_id = ?", (corpus_id,))
            conn.execute("DELETE FROM chunks WHERE corpus_id = ?", (corpus_id,))
        return deleted > 0

    def list_corpora(self) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT corpus_id, name, created_at FROM corpora ORDER BY datetime(created_at) DESC",
            ).fetchall()
            summaries: List[Dict[str, Any]] = []
            for row in rows:
                corpus_id = row["corpus_id"]
                doc_count = conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE corpus_id = ?",
                    (corpus_id,),
                ).fetchone()[0]
                chunk_count = conn.execute(
                    "SELECT COUNT(*) FROM chunks WHERE corpus_id = ?",
                    (corpus_id,),
                ).fetchone()[0]
                summaries.append(
                    {
                        "corpus_id": corpus_id,
                        "name": row["name"],
                        "created_at": row["created_at"],
                        "num_documents": doc_count,
                        "num_chunks": chunk_count,
                    }
                )
        return summaries

    def get_chunk(self, corpus_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT c.chunk_id, c.document_id, c.section_id, c.start_offset, c.end_offset,
                       c.text, c.meta, d.document_name
                FROM chunks c
                JOIN documents d ON d.document_id = c.document_id
                WHERE c.chunk_id = ? AND c.corpus_id = ?
                """,
                (chunk_id, corpus_id),
            ).fetchone()
        if not row:
            return None
        return {
            "chunk_id": row["chunk_id"],
            "document_id": row["document_id"],
            "document_name": row["document_name"],
            "section_id": row["section_id"],
            "start_offset": row["start_offset"],
            "end_offset": row["end_offset"],
            "text": row["text"],
            "meta": json.loads(row["meta"] or "{}"),
        }

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS corpora (
                    corpus_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    chunk_size_chars INTEGER NOT NULL,
                    chunk_overlap_chars INTEGER NOT NULL,
                    meta TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    corpus_id TEXT NOT NULL,
                    document_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    sections TEXT,
                    meta TEXT,
                    FOREIGN KEY (corpus_id) REFERENCES corpora(corpus_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    corpus_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    section_id TEXT,
                    start_offset INTEGER NOT NULL,
                    end_offset INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    meta TEXT,
                    FOREIGN KEY (corpus_id) REFERENCES corpora(corpus_id) ON DELETE CASCADE,
                    FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_corpus ON chunks(corpus_id)"
            )

    @contextmanager
    def _connection(self) -> Iterable[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def create_storage_backend(backend: str = "sqlite", **kwargs: Any) -> StorageBackend:
    if backend == "sqlite":
        db_path = kwargs.get("db_path") or "rlm_corpus.db"
        return SQLiteStorage(db_path=db_path)
    raise ValueError(f"Unknown storage backend '{backend}'")
