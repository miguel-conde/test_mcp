# RLM Corpus Server – Steps 1 to 3

## Goal
Implement the REPL runtime foundation plus the first three MCP tools (`load_corpus`, `open_session`, `exec_repl`, `close_session`) so Copilot can load corpora, open REPL sessions, execute Python code, and cleanly close sessions.

## Prerequisites
Make sure you are on the `feature/rlm-corpus-steps-1-3` branch before beginning implementation.

### Step-by-Step Instructions

#### Step 1: Build the REPL foundation
- [x] Create/overwrite `rlm_corpus_server.py` with the REPL session engine and FastMCP bootstrap below:

```python
from __future__ import annotations

import io
import json
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

CorpusSnapshot = Dict[str, Any]
ContextTuple = Tuple[Any, Any]

SUPPORTED_CONTEXT_VIEWS = {"raw_text", "by_document", "by_chunk"}

app = FastMCP("rlm-corpus-server")

corpora: Dict[str, Any] = {}
sessions: Dict[str, "REPLSession"] = {}


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
        self.created_at = datetime.utcnow()
        self.last_activity_at = self.created_at
        self.exec_count = 0
        self.namespace: Dict[str, Any] = {}

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

        # Ensure canonical handles remain available even if user code overwrote them.
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

        self.last_activity_at = datetime.utcnow()
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
        documents = self.corpus_snapshot.get("documents", [])
        if self.context_view == "raw_text":
            combined = "\n\n".join(doc.get("text", "") for doc in documents)
            meta = {
                "corpus_id": self.corpus_snapshot.get("corpus_id"),
                "num_documents": len(documents),
                "length_chars": len(combined),
            }
            return combined, meta

        if self.context_view == "by_document":
            texts: List[str] = []
            meta: List[Dict[str, Any]] = []
            for doc in documents:
                text = doc.get("text", "")
                texts.append(text)
                meta.append(
                    {
                        "document_id": doc.get("document_id"),
                        "document_name": doc.get("document_name"),
                        "length_chars": len(text),
                        "num_chunks": len(doc.get("chunks", [])),
                    }
                )
            return texts, meta

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


if __name__ == "__main__":
    app.run()
```

- [x] Add the regression test scaffold under `tests/test_repl_contract.py`:

```python
from __future__ import annotations

from typing import Dict, List

from rlm_corpus_server import REPLSession


def _build_snapshot() -> Dict[str, List[Dict[str, str]]]:
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
```


##### Step 1 Verification Checklist
- [ ] `pytest tests/test_repl_contract.py -k repl` passes
- [ ] `llm_query` stub string appears in the test output exports
- [ ] No unexpected files are created during execution

#### Step 1 STOP & COMMIT
**STOP & COMMIT:** Stage and commit the REPL foundation before moving forward.

---

#### Step 2: Add corpus ingestion + session tooling
- [x] Create `corpus_manager.py` with corpus/document/chunk dataclasses plus chunking helpers:

```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List
from uuid import uuid4


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    start_offset: int
    end_offset: int
    meta: Dict[str, Any]
    section_id: str | None = None


@dataclass
class Document:
    document_id: str
    document_name: str
    text: str
    chunks: List[Chunk] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Corpus:
    corpus_id: str
    name: str
    created_at: datetime
    documents: List[Document]
    chunk_size_chars: int
    chunk_overlap_chars: int
    meta: Dict[str, Any] = field(default_factory=dict)


def create_corpus(
    name: str,
    documents: List[Dict[str, str]],
    chunk_size_chars: int = 4000,
    chunk_overlap_chars: int = 400,
) -> Corpus:
    if chunk_size_chars <= 0:
        raise ValueError("chunk_size_chars must be positive")
    if chunk_overlap_chars < 0:
        raise ValueError("chunk_overlap_chars cannot be negative")

    corpus_id = f"corpus-{uuid4().hex}"
    wrapped_documents: List[Document] = []
    for payload in documents:
        document_id = f"doc-{uuid4().hex}"
        document_name = payload.get("document_name") or document_id
        text = payload["text"]
        doc = Document(document_id=document_id, document_name=document_name, text=text)
        doc.chunks = _chunk_document(document_id, text, chunk_size_chars, chunk_overlap_chars)
        doc.meta["num_chunks"] = len(doc.chunks)
        wrapped_documents.append(doc)

    return Corpus(
        corpus_id=corpus_id,
        name=name,
        created_at=datetime.utcnow(),
        documents=wrapped_documents,
        chunk_size_chars=chunk_size_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )


def _chunk_document(
    document_id: str,
    text: str,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    start = 0
    index = 0
    text_length = len(text)
    while start < text_length:
        end = min(start + chunk_size_chars, text_length)
        chunk_text = text[start:end]
        chunk_id = f"chunk-{uuid4().hex}"
        chunk_meta = {
            "index": index,
            "estimated_tokens": max(1, math.ceil(len(chunk_text) / 4)),
        }
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_id=document_id,
                text=chunk_text,
                start_offset=start,
                end_offset=end,
                meta=chunk_meta,
            )
        )
        if end >= text_length:
            break
        start = max(0, end - chunk_overlap_chars)
        index += 1
    return chunks


def count_chunks(corpus: Corpus) -> int:
    return sum(len(doc.chunks) for doc in corpus.documents)


def corpus_to_snapshot(corpus: Corpus) -> Dict[str, Any]:
    documents = []
    for doc in corpus.documents:
        documents.append(
            {
                "document_id": doc.document_id,
                "document_name": doc.document_name,
                "text": doc.text,
                "chunks": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "document_id": chunk.document_id,
                        "text": chunk.text,
                        "start_offset": chunk.start_offset,
                        "end_offset": chunk.end_offset,
                        "section_id": chunk.section_id,
                        "meta": dict(chunk.meta),
                    }
                    for chunk in doc.chunks
                ],
            }
        )
    return {
        "corpus_id": corpus.corpus_id,
        "name": corpus.name,
        "documents": documents,
        "chunk_size_chars": corpus.chunk_size_chars,
        "chunk_overlap_chars": corpus.chunk_overlap_chars,
    }
```

- [x] Replace `rlm_corpus_server.py` with the extended version that wires `load_corpus` and `open_session` MCP tools:

```python
from __future__ import annotations

import io
import json
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from mcp.server.fastmcp import FastMCP, ResponseError

from corpus_manager import Corpus, count_chunks, corpus_to_snapshot, create_corpus

CorpusSnapshot = Dict[str, Any]
ContextTuple = Tuple[Any, Any]

SUPPORTED_CONTEXT_VIEWS = {"raw_text", "by_document", "by_chunk"}

app = FastMCP("rlm-corpus-server")

corpora: Dict[str, Corpus] = {}
sessions: Dict[str, "REPLSession"] = {}


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
        self.created_at = datetime.utcnow()
        self.last_activity_at = self.created_at
        self.exec_count = 0
        self.namespace: Dict[str, Any] = {}

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

        self.last_activity_at = datetime.utcnow()
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
        documents = self.corpus_snapshot.get("documents", [])
        if self.context_view == "raw_text":
            combined = "\n\n".join(doc.get("text", "") for doc in documents)
            meta = {
                "corpus_id": self.corpus_snapshot.get("corpus_id"),
                "num_documents": len(documents),
                "length_chars": len(combined),
            }
            return combined, meta

        if self.context_view == "by_document":
            texts: List[str] = []
            meta: List[Dict[str, Any]] = []
            for doc in documents:
                text = doc.get("text", "")
                texts.append(text)
                meta.append(
                    {
                        "document_id": doc.get("document_id"),
                        "document_name": doc.get("document_name"),
                        "length_chars": len(text),
                        "num_chunks": len(doc.get("chunks", [])),
                    }
                )
            return texts, meta

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


def _normalize_documents(documents: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for idx, item in enumerate(documents):
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ResponseError("invalid_document", f"Document #{idx + 1} is missing text")
        name = item.get("document_name") or item.get("name") or f"document-{idx + 1}"
        normalized.append({"document_name": name, "text": text})
    return normalized


def _get_corpus_or_error(corpus_id: str) -> Corpus:
    corpus = corpora.get(corpus_id)
    if not corpus:
        raise ResponseError("corpus_not_found", f"Corpus '{corpus_id}' does not exist")
    return corpus


@app.tool()
def load_corpus(
    name: str,
    documents: List[Dict[str, str]],
    chunk_size_chars: int = 4000,
    chunk_overlap_chars: int = 400,
) -> Dict[str, Any]:
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
def open_session(
    corpus_id: str,
    context_view: str = "by_chunk",
    enable_llm_query: bool = False,
) -> Dict[str, Any]:
    if context_view not in SUPPORTED_CONTEXT_VIEWS:
        raise ResponseError("invalid_context_view", f"context_view must be one of {sorted(SUPPORTED_CONTEXT_VIEWS)}")

    corpus = _get_corpus_or_error(corpus_id)
    snapshot = corpus_to_snapshot(corpus)
    session = REPLSession(snapshot, context_view=context_view, enable_llm_query=enable_llm_query)
    sessions[session.session_id] = session
    return {
        "session_id": session.session_id,
        "context_view": session.context_view,
        "context_summary": session.context_summary,
    }


if __name__ == "__main__":
    app.run()
```

##### Step 2 Verification Checklist
- [ ] `pytest tests/test_repl_contract.py` still passes
- [ ] `load_corpus` + `open_session` callable via a REPL (e.g., `python -i rlm_corpus_server.py`)
- [ ] MCP server starts without import errors (`python rlm_corpus_server.py`)

#### Step 2 STOP & COMMIT
**STOP & COMMIT:** Capture the corpus ingestion milestone in its own commit before proceeding.

---

- [x] Replace `rlm_corpus_server.py` with the full Step 3 implementation including `exec_repl` and `close_session` MCP tools:

```python
from __future__ import annotations

import io
import json
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from mcp.server.fastmcp import FastMCP, ResponseError

from corpus_manager import Corpus, count_chunks, corpus_to_snapshot, create_corpus

CorpusSnapshot = Dict[str, Any]
ContextTuple = Tuple[Any, Any]

SUPPORTED_CONTEXT_VIEWS = {"raw_text", "by_document", "by_chunk"}

app = FastMCP("rlm-corpus-server")

corpora: Dict[str, Corpus] = {}
sessions: Dict[str, "REPLSession"] = {}


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
        self.created_at = datetime.utcnow()
        self.last_activity_at = self.created_at
        self.exec_count = 0
        self.namespace: Dict[str, Any] = {}

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

        self.last_activity_at = datetime.utcnow()
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
        documents = self.corpus_snapshot.get("documents", [])
        if self.context_view == "raw_text":
            combined = "\n\n".join(doc.get("text", "") for doc in documents)
            meta = {
                "corpus_id": self.corpus_snapshot.get("corpus_id"),
                "num_documents": len(documents),
                "length_chars": len(combined),
            }
            return combined, meta

        if self.context_view == "by_document":
            texts: List[str] = []
            meta: List[Dict[str, Any]] = []
            for doc in documents:
                text = doc.get("text", "")
                texts.append(text)
                meta.append(
                    {
                        "document_id": doc.get("document_id"),
                        "document_name": doc.get("document_name"),
                        "length_chars": len(text),
                        "num_chunks": len(doc.get("chunks", [])),
                    }
                )
            return texts, meta

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


def _normalize_documents(documents: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for idx, item in enumerate(documents):
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ResponseError("invalid_document", f"Document #{idx + 1} is missing text")
        name = item.get("document_name") or item.get("name") or f"document-{idx + 1}"
        normalized.append({"document_name": name, "text": text})
    return normalized


def _get_corpus_or_error(corpus_id: str) -> Corpus:
    corpus = corpora.get(corpus_id)
    if not corpus:
        raise ResponseError("corpus_not_found", f"Corpus '{corpus_id}' does not exist")
    return corpus


def _get_session_or_error(session_id: str) -> "REPLSession":
    session = sessions.get(session_id)
    if not session:
        raise ResponseError("session_not_found", f"Session '{session_id}' does not exist")
    return session


@app.tool()
def load_corpus(
    name: str,
    documents: List[Dict[str, str]],
    chunk_size_chars: int = 4000,
    chunk_overlap_chars: int = 400,
) -> Dict[str, Any]:
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
def open_session(
    corpus_id: str,
    context_view: str = "by_chunk",
    enable_llm_query: bool = False,
) -> Dict[str, Any]:
    if context_view not in SUPPORTED_CONTEXT_VIEWS:
        raise ResponseError("invalid_context_view", f"context_view must be one of {sorted(SUPPORTED_CONTEXT_VIEWS)}")

    corpus = _get_corpus_or_error(corpus_id)
    snapshot = corpus_to_snapshot(corpus)
    session = REPLSession(snapshot, context_view=context_view, enable_llm_query=enable_llm_query)
    sessions[session.session_id] = session
    return {
        "session_id": session.session_id,
        "context_view": session.context_view,
        "context_summary": session.context_summary,
    }


@app.tool()
def exec_repl(
    session_id: str,
    code: str,
    capture_variables: List[str] | None = None,
) -> Dict[str, Any]:
    if not code or not code.strip():
        raise ResponseError("invalid_request", "code must be a non-empty string")
    session = _get_session_or_error(session_id)
    return session.execute(code, capture_variables)


@app.tool()
def close_session(session_id: str) -> Dict[str, Any]:
    removed = sessions.pop(session_id, None)
    return {"closed": removed is not None}


if __name__ == "__main__":
    app.run()
```

- [x] Replace `tests/test_repl_contract.py` with the stronger Step 3 coverage:

```python
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
```

-
##### Step 3 Verification Checklist (status)
- [x] `pytest tests/test_repl_contract.py` passes — 5 tests passing locally
- [x] `python rlm_corpus_server.py` starts the MCP server without import errors (safe fallback present)
- [x] Manual smoke test: `open_session` + `exec_repl` exercised via unit tests and REPL smoke runs

**Implementation Status**
- Branch: `feature/rlm-corpus-steps-1-3`
- Commits: Step1 (886db1f), Step2 (7edf595), Step3 (857dccd), tz-fix (f124bc2)
- Static checks: `mypy .` → success
- Tests: `PYTHONPATH=. pytest -q` → all tests passing

**Notes**
- `rlm_corpus_server.py` includes safe fallbacks for environments without `mcp` so unit tests run without the full MCP runtime installed.
- `corpus_manager.py` and `rlm_corpus_server.py` use timezone-aware datetimes to avoid deprecation warnings.

#### Step 3 STOP & COMMIT
**STOP & COMMIT:** After validating exec/close behavior, stage and commit the Step 3 implementation.
