"""RLM corpus MCP server with REPL-style execution sessions.

This module implements an MCP server exposing corpus navigation and a
stateful REPL environment for programmatic corpus mining.
"""

from __future__ import annotations

import io
import json
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, cast
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

CorpusSnapshot = Dict[str, Any]
ContextTuple = Tuple[Any, Any]

SUPPORTED_CONTEXT_VIEWS = {"raw_text", "by_document", "by_chunk"}

# Initialize FastMCP server
app = FastMCP("rlm-corpus-server")

corpora: Dict[str, Any] = {}
sessions: Dict[str, "REPLSession"] = {}

# Add current directory to Python path for imports
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from corpus_manager import (
        Corpus,
        count_chunks,
        corpus_to_snapshot,
        create_corpus,
        create_documents,
    )
except ImportError as e:
    print(f"[ERROR] Failed to import corpus_manager: {e}", file=sys.stderr)
    print(f"[DEBUG] Working directory: {Path.cwd()}", file=sys.stderr)
    print(f"[DEBUG] Script location: {Path(__file__).parent}", file=sys.stderr)
    raise


def _normalize_documents(documents: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for idx, item in enumerate(documents):
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Document #{idx + 1} is missing text")
        name = item.get("document_name") or item.get("name") or f"document-{idx + 1}"
        normalized.append({"document_name": name, "text": text})
    return normalized


def _get_corpus_or_error(corpus_id: str) -> Any:
    corpus = corpora.get(corpus_id)
    if not corpus:
        raise ValueError(f"Corpus '{corpus_id}' does not exist")
    return corpus


def _get_session_or_error(session_id: str) -> "REPLSession":
    session = sessions.get(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' does not exist")
    return session



class REPLSession:
    """Stateful Python execution environment bound to a corpus snapshot."""

    def __init__(
        self,
        corpus_snapshot: CorpusSnapshot,
        context_view: str = "by_chunk",
        enable_llm_query: bool = False,
    ) -> None:
        if context_view not in SUPPORTED_CONTEXT_VIEWS:
            raise ValueError(
                f"context_view '{context_view}' is not supported. "
                f"Valid options: {sorted(SUPPORTED_CONTEXT_VIEWS)}"
            )

        self.session_id = f"session-{uuid4().hex}"
        self.corpus_snapshot = corpus_snapshot
        self.context_view = context_view
        self.enable_llm_query = enable_llm_query
        self.created_at = datetime.now(timezone.utc)
        self.last_activity_at = self.created_at
        self.exec_count = 0
        self.namespace: Dict[str, Any] = {}
        # Typed placeholders to satisfy static checkers prior to materialization
        self.context: Any = None
        self.context_meta: Any = None
        self.context, self.context_meta = self._materialize_context()
        self.namespace["context"] = self.context
        self.namespace["context_meta"] = self.context_meta
        self.namespace["llm_query"] = self._default_llm_query
        self._context_summary = self._calculate_context_summary()

    @property
    def context_summary(self) -> Dict[str, Any]:
        return dict(self._context_summary)

    def execute(
        self,
        code: str,
        capture_variables: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Execute Python code inside the session namespace."""

        capture_variables = capture_variables or []
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        globals_dict: Dict[str, Any] = {"__builtins__": __builtins__}  # type: ignore[name-defined]
        locals_dict = self.namespace
        locals_dict["context"] = self.context
        locals_dict["context_meta"] = self.context_meta
        locals_dict["llm_query"] = self._default_llm_query

        try:
            sys.stdout, sys.stderr = stdout_buffer, stderr_buffer
            exec(code, globals_dict, locals_dict)
        except Exception:
            traceback.print_exc(file=stderr_buffer)
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__

        self.last_activity_at = datetime.now(timezone.utc)
        self.exec_count += 1
        exports = self._collect_exports(capture_variables)

        return {
            "stdout": stdout_buffer.getvalue(),
            "stderr": stderr_buffer.getvalue(),
            "truncated": False,
            "exports": exports,
            "usage": {
                "exec_count": self.exec_count,
                "last_activity_at": self.last_activity_at.isoformat(),
            },
        }

    def _materialize_context(self) -> ContextTuple:
        documents = cast(List[Dict[str, Any]], self.corpus_snapshot.get("documents", []))
        if self.context_view == "raw_text":
            combined: str = "\n\n".join(doc.get("text", "") for doc in documents)
            raw_meta: Dict[str, Any] = {
                "corpus_id": self.corpus_snapshot.get("corpus_id"),
                "num_documents": len(documents),
                "length_chars": len(combined),
            }
            return combined, raw_meta

        if self.context_view == "by_document":
            texts: List[str] = []
            docs_meta: List[Dict[str, Any]] = []
            for doc in documents:
                text = doc.get("text", "")
                texts.append(text)
                docs_meta.append(
                    {
                        "document_id": doc.get("document_id"),
                        "document_name": doc.get("document_name"),
                        "length_chars": len(text),
                        "num_chunks": len(doc.get("chunks", [])),
                    }
                )
            return texts, docs_meta

        # Default: by_chunk
        chunk_texts: List[str] = []
        chunk_meta: List[Dict[str, Any]] = []
        for doc in documents:
            for chunk in doc.get("chunks", []):
                chunk_texts.append(chunk.get("text", ""))
                chunk_meta.append(
                    {
                        "chunk_id": chunk.get("chunk_id"),
                        "document_id": chunk.get("document_id"),
                        "section_id": chunk.get("section_id"),
                        "index": chunk.get("meta", {}).get("index"),
                        "start_offset": chunk.get("start_offset"),
                        "end_offset": chunk.get("end_offset"),
                        "estimated_tokens": chunk.get("meta", {}).get("estimated_tokens"),
                    }
                )
        return chunk_texts, chunk_meta

    def _calculate_context_summary(self) -> Dict[str, Any]:
        total_chars = sum(len(doc.get("text", "")) for doc in self.corpus_snapshot.get("documents", []))
        item_count = len(self.context) if isinstance(self.context, list) else 1
        return {
            "corpus_id": self.corpus_snapshot.get("corpus_id"),
            "context_view": self.context_view,
            "items": item_count,
            "total_chars": total_chars,
        }

    def _collect_exports(self, capture_variables: List[str]) -> Dict[str, str]:
        exports: Dict[str, str] = {}
        for var in capture_variables:
            if var in self.namespace:
                exports[var] = self._stringify(self.namespace[var])
        return exports

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)) or value is None:
            return json.dumps(value, ensure_ascii=False)
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            return repr(value)

    @staticmethod
    def _default_llm_query(prompt: str) -> str:
        snippet = prompt[:80].replace("\n", " ")
        return f"[STUB: sub-analysis needed for: {snippet}...]"


@app.tool()
def exec_repl(
    session_id: str,
    code: str,
    capture_variables: List[str] | None = None,
) -> Dict[str, Any]:
    """Execute Python code in a REPL session."""
    if not code or not code.strip():
        raise ValueError("code must be a non-empty string")
    session = _get_session_or_error(session_id)
    return session.execute(code, capture_variables)


@app.tool()
def close_session(session_id: str) -> Dict[str, Any]:
    """Close a REPL session."""
    removed = sessions.pop(session_id, None)
    return {"closed": removed is not None}


@app.tool()
def load_corpus(
    name: str,
    documents: List[Dict[str, str]],
    chunk_size_chars: int = 4000,
    chunk_overlap_chars: int = 400,
) -> Dict[str, Any]:
    """Create a Corpus from documents and register it in-memory."""
    normalized_docs = _normalize_documents(documents)
    corpus = create_corpus(
        name=name,
        documents=normalized_docs,
        chunk_size_chars=chunk_size_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )
    corpora[corpus.corpus_id] = corpus
    return {
        "corpus_id": corpus.corpus_id,
        "name": corpus.name,
        "num_documents": len(corpus.documents),
        "num_chunks": count_chunks(corpus),
        "chunk_size_chars": corpus.chunk_size_chars,
        "chunk_overlap_chars": corpus.chunk_overlap_chars,
    }


@app.tool()
def append_documents(
    corpus_id: str,
    documents: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Append new documents to an existing corpus.

    Args:
        corpus_id: Identifier for the corpus to extend.
        documents: Document payloads to append.

    Returns:
        Summary of append operation including counts and new document info.

    Raises:
        ValueError: If the corpus is missing or the documents are invalid.
    """
    if not isinstance(documents, list) or not documents:
        raise ValueError("documents must be a non-empty list")

    corpus = _get_corpus_or_error(corpus_id)
    num_documents_before = len(corpus.documents)
    num_chunks_before = count_chunks(corpus)

    normalized_docs = _normalize_documents(documents)
    new_documents = create_documents(
        normalized_docs,
        chunk_size_chars=corpus.chunk_size_chars,
        chunk_overlap_chars=corpus.chunk_overlap_chars,
    )
    corpus.documents.extend(new_documents)

    added_num_chunks = sum(len(doc.chunks) for doc in new_documents)
    return {
        "corpus_id": corpus_id,
        "num_documents_before": num_documents_before,
        "num_documents_after": len(corpus.documents),
        "num_chunks_before": num_chunks_before,
        "num_chunks_after": count_chunks(corpus),
        "added": {
            "num_documents": len(new_documents),
            "num_chunks": added_num_chunks,
        },
        "documents": [
            {
                "document_id": doc.document_id,
                "document_name": doc.document_name,
                "num_chunks": len(doc.chunks),
            }
            for doc in new_documents
        ],
    }


@app.tool()
def open_session(
    corpus_id: str,
    context_view: str = "by_chunk",
    enable_llm_query: bool = False,
) -> Dict[str, Any]:
    """Open a new REPL session for corpus analysis."""
    if context_view not in SUPPORTED_CONTEXT_VIEWS:
        raise ValueError(f"context_view must be one of {sorted(SUPPORTED_CONTEXT_VIEWS)}")

    corpus = _get_corpus_or_error(corpus_id)
    snapshot = corpus_to_snapshot(corpus)
    session = REPLSession(snapshot, context_view=context_view, enable_llm_query=enable_llm_query)
    sessions[session.session_id] = session
    return {
        "session_id": session.session_id,
        "context_view": session.context_view,
        "context_summary": session.context_summary,
    }


def _iter_document_chunks(corpus: "Corpus"):
    for document in corpus.documents:
        for chunk in document.chunks:
            yield document, chunk


def _build_chunk_payload(corpus_id: str, document: Any, chunk: Any, *, with_meta: bool = True) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "corpus_id": corpus_id,
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "document_name": getattr(document, "document_name", None),
        "text": chunk.text,
    }
    if with_meta:
        payload["meta"] = {
            "section_id": getattr(chunk, "section_id", None),
            "index": chunk.meta.get("index"),
            "start_offset": getattr(chunk, "start_offset", None),
            "end_offset": getattr(chunk, "end_offset", None),
            "estimated_tokens": chunk.meta.get("estimated_tokens"),
        }
    return payload


def _find_chunk(corpus: "Corpus", chunk_id: str):
    for document, chunk in _iter_document_chunks(corpus):
        if chunk.chunk_id == chunk_id:
            return document, chunk
    return None, None


@app.tool()
def search_corpus(
    corpus_id: str,
    query: str,
    top_k: int = 10,
    snippet_radius: int = 80,
    case_sensitive: bool = False,
    semantic: bool = False,
) -> Dict[str, Any]:
    """Search chunk texts for literal matches."""
    if semantic:
        raise ValueError("semantic search is not supported yet")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if snippet_radius < 0:
        raise ValueError("snippet_radius cannot be negative")

    corpus = _get_corpus_or_error(corpus_id)
    # lazy import to avoid circular issues in some environments
    from search_engine import literal_search_chunks

    results = literal_search_chunks(
        corpus=corpus,
        query=query,
        top_k=top_k,
        case_sensitive=case_sensitive,
        snippet_radius=snippet_radius,
    )
    return {
        "corpus_id": corpus_id,
        "query": query,
        "results": results,
    }


@app.tool()
def get_chunk(corpus_id: str, chunk_id: str, with_meta: bool = True) -> Dict[str, Any]:
    """Fetch the text and metadata for a specific chunk."""
    if not chunk_id or not chunk_id.strip():
        raise ValueError("chunk_id must be a non-empty string")

    corpus = _get_corpus_or_error(corpus_id)
    document, chunk = _find_chunk(corpus, chunk_id)
    if not chunk or not document:
        raise ValueError(f"Chunk '{chunk_id}' does not exist in corpus '{corpus_id}'")
    return _build_chunk_payload(corpus_id, document, chunk, with_meta=with_meta)


def _describe_document(document: Any, *, include_chunks: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "document_id": document.document_id,
        "document_name": document.document_name,
        "length_chars": len(document.text),
        "num_chunks": len(document.chunks),
        "estimated_tokens": sum(chunk.meta.get("estimated_tokens", 0) for chunk in document.chunks),
    }
    if include_chunks:
        payload["chunks"] = [
            {
                "chunk_id": chunk.chunk_id,
                "section_id": getattr(chunk, "section_id", None),
                "start_offset": getattr(chunk, "start_offset", None),
                "end_offset": getattr(chunk, "end_offset", None),
                "estimated_tokens": chunk.meta.get("estimated_tokens"),
            }
            for chunk in document.chunks
        ]
    return payload


@app.tool()
def list_corpus() -> Dict[str, Any]:
    """List all in-memory corpora with summary metadata."""
    summaries: List[Dict[str, Any]] = []
    for corpus in corpora.values():
        summaries.append(
            {
                "corpus_id": corpus.corpus_id,
                "name": corpus.name,
                "num_documents": len(corpus.documents),
                "num_chunks": count_chunks(corpus),
                "chunk_size_chars": corpus.chunk_size_chars,
                "chunk_overlap_chars": corpus.chunk_overlap_chars,
                "loaded_at": corpus.created_at.isoformat(),
            }
        )
    summaries.sort(key=lambda item: item["loaded_at"], reverse=True)
    return {"corpora": summaries}


@app.tool()
def describe_corpus(corpus_id: str, include_documents: bool = False, include_chunks: bool = False) -> Dict[str, Any]:
    """Return detailed metadata for a corpus."""
    corpus = _get_corpus_or_error(corpus_id)
    payload: Dict[str, Any] = {
        "corpus_id": corpus.corpus_id,
        "name": corpus.name,
        "num_documents": len(corpus.documents),
        "num_chunks": count_chunks(corpus),
        "chunk_size_chars": corpus.chunk_size_chars,
        "chunk_overlap_chars": corpus.chunk_overlap_chars,
    }
    if include_documents:
        payload["documents"] = [
            _describe_document(document, include_chunks=include_chunks)
            for document in corpus.documents
        ]
    return payload


@app.tool()
def delete_corpus(corpus_id: str, *, force: bool = False) -> Dict[str, Any]:
    """Delete a corpus and any sessions that reference it."""
    corpus = corpora.get(corpus_id)
    if not corpus:
        raise ValueError(f"Corpus '{corpus_id}' does not exist")
    if not force:
        active_sessions = [
            session_id
            for session_id, session in sessions.items()
            if (getattr(session, "corpus_id", None) or session.corpus_snapshot.get("corpus_id")) == corpus_id
        ]
        if active_sessions:
            raise ValueError(
                "Cannot delete corpus with active sessions. "
                "Pass force=True to close sessions automatically."
            )
    to_remove = [
        session_id
        for session_id, session in sessions.items()
        if (getattr(session, "corpus_id", None) or session.corpus_snapshot.get("corpus_id")) == corpus_id
    ]
    for session_id in to_remove:
        sessions.pop(session_id, None)
    corpora.pop(corpus_id, None)
    return {"deleted": True, "sessions_closed": len(to_remove)}


@app.tool()
def list_chunks(
    corpus_id: str,
    document_id: str | None = None,
    section_id: str | None = None,
    limit: int = 200,
    include_text: bool = False,
) -> Dict[str, Any]:
    """Return chunk metadata for a corpus (optionally filtered)."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    corpus = _get_corpus_or_error(corpus_id)
    items: List[Dict[str, Any]] = []
    for document, chunk in _iter_document_chunks(corpus):
        if document_id and chunk.document_id != document_id:
            continue
        if section_id and chunk.section_id != section_id:
            continue
        entry: Dict[str, Any] = {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "document_name": document.document_name,
            "section_id": chunk.section_id,
            "start_offset": chunk.start_offset,
            "end_offset": chunk.end_offset,
            "estimated_tokens": chunk.meta.get("estimated_tokens"),
        }
        if include_text:
            entry["text"] = chunk.text
        items.append(entry)
        if len(items) >= limit:
            break
    return {
        "corpus_id": corpus_id,
        "document_id": document_id,
        "section_id": section_id,
        "limit": limit,
        "chunks": items,
        "total_returned": len(items),
    }


if __name__ == "__main__":
    app.run()
