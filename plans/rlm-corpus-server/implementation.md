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

---

# RLM Corpus Server – Steps 4 to 6

## Goal
Add the navigation, corpus management, and chunk-listing MCP tools (`search_corpus`, `get_chunk`, `list_corpus`, `describe_corpus`, `delete_corpus`, `list_chunks`) so Copilot can quickly locate relevant snippets, inspect corpus metadata, and enumerate chunk structures before executing REPL workflows.

## Prerequisites
Make sure you are on the `feature/rlm-corpus-steps-4-6` branch before beginning implementation.

### Step-by-Step Instructions

#### Step 4: Implement `search_corpus` and `get_chunk` navigation tools
- [ ] Add the literal search helper module at `search_engine.py`:

```python
"""Literal search helpers for the RLM corpus server."""

from __future__ import annotations

from typing import Any, Dict, List

from corpus_manager import Corpus


def literal_search_chunks(
    corpus: Corpus,
    query: str,
    *,
    top_k: int = 10,
    case_sensitive: bool = False,
    snippet_radius: int = 80,
) -> List[Dict[str, Any]]:
    """Return the top chunk matches for a literal query."""
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if snippet_radius < 0:
        raise ValueError("snippet_radius cannot be negative")

    normalized_query = query if case_sensitive else query.lower()
    results: List[Dict[str, Any]] = []
    for document in corpus.documents:
        for chunk in document.chunks:
            text = chunk.text
            haystack = text if case_sensitive else text.lower()
            hit_count = haystack.count(normalized_query)
            if hit_count == 0:
                continue
            first_index = haystack.find(normalized_query)
            snippet = _build_snippet(text, first_index, len(query), snippet_radius)
            results.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "section_id": chunk.section_id,
                    "score": hit_count,
                    "snippet": snippet,
                }
            )

    results.sort(key=lambda item: (-item["score"], item["chunk_id"]))
    return results[:top_k]


def _build_snippet(
    text: str,
    start_index: int,
    match_length: int,
    snippet_radius: int,
) -> str:
    if start_index < 0:
        start_index = 0
    start = max(0, start_index - snippet_radius)
    end = min(len(text), start_index + match_length + snippet_radius)
    snippet = text[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"
```

- [ ] Replace `rlm_corpus_server.py` with the navigation-ready version below:

```python
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
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, cast
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from corpus_manager import (
    Chunk,
    Corpus,
    Document,
    count_chunks,
    corpus_to_snapshot,
    create_corpus,
)
from search_engine import literal_search_chunks

CorpusSnapshot = Dict[str, Any]
ContextTuple = Tuple[Any, Any]

SUPPORTED_CONTEXT_VIEWS = {"raw_text", "by_document", "by_chunk"}

app = FastMCP("rlm-corpus-server")

corpora: Dict[str, Corpus] = {}
sessions: Dict[str, "REPLSession"] = {}

sys.path.insert(0, str(Path(__file__).parent))


def _normalize_documents(documents: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for idx, item in enumerate(documents):
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Document #{idx + 1} is missing text")
        name = item.get("document_name") or item.get("name") or f"document-{idx + 1}"
        normalized.append({"document_name": name, "text": text})
    return normalized


def _get_corpus_or_error(corpus_id: str) -> Corpus:
    corpus = corpora.get(corpus_id)
    if not corpus:
        raise ValueError(f"Corpus '{corpus_id}' does not exist")
    return cast(Corpus, corpus)


def _get_session_or_error(session_id: str) -> "REPLSession":
    session = sessions.get(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' does not exist")
    return session


def _iter_document_chunks(corpus: Corpus) -> Iterable[Tuple[Document, Chunk]]:
    for document in corpus.documents:
        for chunk in document.chunks:
            yield document, chunk


def _build_chunk_payload(
    corpus_id: str,
    document: Document,
    chunk: Chunk,
    *,
    with_meta: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "corpus_id": corpus_id,
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "document_name": document.document_name,
        "text": chunk.text,
    }
    if with_meta:
        payload["meta"] = {
            "section_id": chunk.section_id,
            "index": chunk.meta.get("index"),
            "start_offset": chunk.start_offset,
            "end_offset": chunk.end_offset,
            "estimated_tokens": chunk.meta.get("estimated_tokens"),
        }
    return payload


def _find_chunk(corpus: Corpus, chunk_id: str) -> Tuple[Document | None, Chunk | None]:
    for document, chunk in _iter_document_chunks(corpus):
        if chunk.chunk_id == chunk_id:
            return document, chunk
    return None, None


class REPLSession:
    """Stateful Python execution environment bound to a corpus snapshot."""

    def __init__(
        self,
        corpus_snapshot: CorpusSnapshot,
        context_view: str = "by_chunk",
        enable_llm_query: bool = False,
        corpus_id: str | None = None,
    ) -> None:
        if context_view not in SUPPORTED_CONTEXT_VIEWS:
            raise ValueError(
                f"context_view '{context_view}' is not supported. "
                f"Valid options: {sorted(SUPPORTED_CONTEXT_VIEWS)}"
            )

        self.session_id = f"session-{uuid4().hex}"
        self.corpus_id = corpus_id or cast(str, corpus_snapshot.get("corpus_id"))
        self.corpus_snapshot = corpus_snapshot
        self.context_view = context_view
        self.enable_llm_query = enable_llm_query
        self.created_at = datetime.now(timezone.utc)
        self.last_activity_at = self.created_at
        self.exec_count = 0
        self.namespace: Dict[str, Any] = {}
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
    session = REPLSession(
        snapshot,
        context_view=context_view,
        enable_llm_query=enable_llm_query,
        corpus_id=corpus.corpus_id,
    )
    sessions[session.session_id] = session
    return {
        "session_id": session.session_id,
        "context_view": session.context_view,
        "context_summary": session.context_summary,
    }


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
def get_chunk(
    corpus_id: str,
    chunk_id: str,
    with_meta: bool = True,
) -> Dict[str, Any]:
    """Fetch the text and metadata for a specific chunk."""
    if not chunk_id or not chunk_id.strip():
        raise ValueError("chunk_id must be a non-empty string")

    corpus = _get_corpus_or_error(corpus_id)
    document, chunk = _find_chunk(corpus, chunk_id)
    if not chunk or not document:
        raise ValueError(f"Chunk '{chunk_id}' does not exist in corpus '{corpus_id}'")
    return _build_chunk_payload(corpus_id, document, chunk, with_meta=with_meta)


if __name__ == "__main__":
    app.run()
```

- [ ] Add navigation regression tests at `tests/test_navigation_tools.py`:

```python
from __future__ import annotations

import pytest

import rlm_corpus_server as server


SAMPLE_TEXT = (
    "Fusion energy programs continue to grow and evolve.\n"
    "Researchers study fusion stability and energy capture across labs.\n"
    "Modern labs catalog discoveries about FUSION techniques and safety.\n"
) * 80


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
```

##### Step 4 Verification Checklist
- [ ] `PYTHONPATH=. pytest tests/test_navigation_tools.py -k "search or chunk"`
- [ ] `PYTHONPATH=. pytest tests/test_repl_contract.py -k repl`

#### Step 4 STOP & COMMIT
**STOP & COMMIT:** Stage, review, and commit all Step 4 changes before proceeding.

---

#### Step 5: Add corpus catalog & lifecycle utilities
- [ ] Extend `rlm_corpus_server.py` with the metadata helper and management tools:

```python
# New helper near _build_chunk_payload

def _describe_document(
    document: Document,
    *,
    include_chunks: bool = False,
) -> Dict[str, Any]:
    payload = {
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
                "section_id": chunk.section_id,
                "start_offset": chunk.start_offset,
                "end_offset": chunk.end_offset,
                "estimated_tokens": chunk.meta.get("estimated_tokens"),
            }
            for chunk in document.chunks
        ]
    return payload
```

```python
@app.tool()
def list_corpus() -> Dict[str, Any]:
    """List all in-memory corpora with summary metadata."""
    summaries = []
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
def describe_corpus(
    corpus_id: str,
    include_documents: bool = False,
    include_chunks: bool = False,
) -> Dict[str, Any]:
    """Return detailed metadata for a corpus."""
    corpus = _get_corpus_or_error(corpus_id)
    payload = {
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
            session_id for session_id, session in sessions.items() if session.corpus_id == corpus_id
        ]
        if active_sessions:
            raise ValueError(
                "Cannot delete corpus with active sessions. "
                "Pass force=True to close sessions automatically."
            )
    to_remove = [session_id for session_id, session in sessions.items() if session.corpus_id == corpus_id]
    for session_id in to_remove:
        sessions.pop(session_id, None)
    corpora.pop(corpus_id, None)
    return {"deleted": True, "sessions_closed": len(to_remove)}
```

- [ ] Add regression coverage at `tests/test_corpus_management_tools.py`:

```python
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
```

##### Step 5 Verification Checklist
- [ ] `PYTHONPATH=. pytest tests/test_corpus_management_tools.py`
- [ ] `PYTHONPATH=. pytest tests/test_navigation_tools.py -k "search or chunk"`
- [ ] `PYTHONPATH=. pytest tests/test_rlm_workflow.py`

#### Step 5 STOP & COMMIT
**STOP & COMMIT:** Stage, review, and commit all Step 5 changes before moving forward.

---

#### Step 6: Implement chunk enumeration (`list_chunks`) for pre-REPL inspection
- [ ] Extend `rlm_corpus_server.py` with the chunk listing tool:

```python
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
        entry = {
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
```

- [ ] Add regression coverage at `tests/test_chunk_listing.py`:

```python
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
```

##### Step 6 Verification Checklist
- [ ] `PYTHONPATH=. pytest tests/test_chunk_listing.py`
- [ ] `PYTHONPATH=. pytest tests/test_corpus_management_tools.py`
- [ ] `PYTHONPATH=. pytest tests/test_navigation_tools.py`
- [ ] `PYTHONPATH=. pytest tests/test_rlm_workflow.py`

#### Step 6 STOP & COMMIT
**STOP & COMMIT:** Stage, review, and commit all Step 6 changes, then open a PR for `feature/rlm-corpus-steps-4-6`.

---

# RLM Corpus Server – Steps 9 to 11

## Goal
Document the MCP setup flow, wire the experimental `llm_query` integration, and expose section-detection helpers so Copilot can operate the corpus server end-to-end from VS Code, opt into recursive LLM calls, and inspect logical document structure.

## Prerequisites
- Switch to the `feature/rlm-corpus-steps-9-11` branch.
- Steps 1–8 must already be merged into this branch; reuse their helpers/tests.

### Step-by-Step Instructions

#### Step 9: Author MCP configuration and setup docs
- [ ] Update `README.md` with a short “Run with VS Code MCP” section that links to the new setup guide and mentions the sample `mcp.json` file.
- [ ] Create `docs/setup_mcp.md` describing:
    - How to create/activate the virtualenv (`python -m venv .venv && source .venv/bin/activate`).
    - Installing dependencies with `pip install -r requirements.txt`.
    - Copying `.vscode/mcp.json.example` to `~/.config/Code/User/mcp.json` (or `%APPDATA%/Code/User/mcp.json` on Windows) and editing absolute paths.
    - Required environment variables (`OPENAI_API_KEY` only needed for Step 10 experimental mode) and how to inject them via the `env` block.
    - Verifying the server inside Copilot Chat by typing `@rlm-corpus-server` and running a `load_corpus → search_corpus → exec_repl` smoke flow.
- [ ] Add `.vscode/mcp.json.example` mirroring the snippet from the plan:

```json
{
    "servers": {
        "rlm-corpus-server": {
            "command": "/absolute/path/to/.venv/bin/python",
            "args": ["/absolute/path/to/rlm_corpus_server.py"],
            "env": {
                "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
            }
        }
    }
}
```

- [x] When documenting workflow examples, explicitly walk through: attaching a file to Copilot Chat, calling `load_corpus`, asking for `search_corpus` with a keyword, and finally issuing a prompt that triggers `exec_repl`. Mention that `llm_query` stays stubbed unless experimental mode is enabled.
- [x] Proofread the guide to ensure commands copy/paste cleanly on macOS/Linux.

##### Step 9 Verification Checklist
- [x] `markdownlint` (if available) passes on the updated docs.
- [x] Copilot Chat detects `@rlm-corpus-server` after placing the sample config (manual smoke test).
- [x] All documentation links resolve locally.

#### Step 10: Wire experimental OpenAI-backed `llm_query`
- [x] Append `openai>=1.6.0` (or the version used elsewhere in the repo) to `requirements.txt` and run `pip install -r requirements.txt` to refresh the lockstep environment.
- [x] In `rlm_corpus_server.py`:
    - Import `os` and the OpenAI SDK (`from openai import OpenAI`).
    - Teach `REPLSession` to capture `enable_llm_query` and lazily build a callable via a `_build_llm_query()` helper. Only expose the real function when `enable_llm_query=True`; otherwise keep returning the existing stub so unit tests do not require the API key.
    - Inside `_build_llm_query`, fetch `OPENAI_API_KEY` from the environment once, initialize `OpenAI(api_key=...)`, and return a closure that calls `client.responses.create` or `client.chat.completions.create` (plan suggests `gpt-4o-mini`, `temperature=0.2`, `max_tokens≈1024`). Catch `Exception` and stringify the error rather than raising inside the REPL.
    - Update `open_session` so the response payload advertises whether `llm_query` is real (e.g., include `"llm_query_mode": "openai" | "stub"`).
    - Add a guard that raises a `ResponseError("missing_api_key", ...)` when `enable_llm_query=True` but no `OPENAI_API_KEY` is present.
- [x] Extend `tests/test_repl_contract.py` (or add a new `tests/test_llm_query_experimental.py`) with a test that monkeypatches `os.getenv`/`OpenAI` to avoid hitting the network. The test should:
    - Set `enable_llm_query=True` when calling `open_session`.
    - Execute code that calls `llm_query("Explain fusion context")` and assert the mocked client returns the canned string.
    - Verify `llm_query` gracefully surfaces exceptions (mock raising `RuntimeError` → export contains `ERROR:` prefix).
- [x] Document trade-offs in `docs/llm_query_experimental.md`: cost implications, recommended usage (only when the root LM cannot orchestrate recursion externally), and toggle instructions.

##### Step 10 Verification Checklist
- [x] `PYTHONPATH=. pytest tests/test_repl_contract.py -k llm_query` (or the new dedicated test file) passes with the mocks.
- [x] `ruff check rlm_corpus_server.py` (or your linter) stays clean.
- [x] Running `open_session(..., enable_llm_query=False)` still injects the stub without needing an API key.

#### Step 11: Add heading detection and `list_sections`
- [ ] Create `section_detector.py` with the regex-driven helper from the plan:

```python
from __future__ import annotations

import re
from typing import Any, Dict, List

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def detect_sections(text: str, *, max_level: int = 6) -> List[Dict[str, Any]]:
    if max_level < 1:
        raise ValueError("max_level must be positive")
    sections: List[Dict[str, Any]] = []
    for match in HEADING_PATTERN.finditer(text):
        level = len(match.group(1))
        if level > max_level:
            continue
        sections.append(
            {
                "level": level,
                "title": match.group(2).strip(),
                "start_offset": match.start(),
            }
        )
    for idx, section in enumerate(sections):
        section["end_offset"] = sections[idx + 1]["start_offset"] if idx + 1 < len(sections) else len(text)
    return sections
```

- [ ] Update `corpus_manager.Document` to store an optional `sections: List[Dict[str, Any]]` so detection results can be cached per document when loading/append.
- [ ] When chunking (in `_chunk_document` or directly after), associate `chunk.section_id` by locating the section whose `[start_offset, end_offset)` contains the chunk’s midpoint. Keep it lightweight (linear scan works for now).
- [ ] Extend `rlm_corpus_server.py`:
    - Import `detect_sections` and compute sections when creating/ appending documents; persist them in the corpus snapshot so REPL context_meta already references section IDs.
    - Add the `@app.tool()` `list_sections(corpus_id: str, document_id: str | None = None, max_level: int = 3)` implementation from the plan. It should iterate documents, run/cached `detect_sections`, filter by `document_id`, clamp to `max_level`, and return payloads shaped like:

```jsonc
{
    "sections": [
        {
            "document_id": "doc-...",
            "document_name": "doc.md",
            "level": 2,
            "title": "Background",
            "start_offset": 1200,
            "end_offset": 2450,
            "chunk_ids": ["chunk-...", "chunk-..."]
        }
    ]
}
```

    - Each section entry should include the chunk IDs intersecting its offsets so root LMs can quickly open the right chunks.
- [ ] Add unit tests (`tests/test_section_detector.py` and `tests/test_list_sections.py`) that cover:
    - `detect_sections` parsing multiple heading levels and respecting `max_level`.
    - `list_sections` returning sections for every document, filtering by `document_id`, and wiring `chunk_ids` correctly.
- [ ] Update `list_chunks` documentation/tests to highlight the new `section_id` values now that headings are available.

##### Step 11 Verification Checklist
- [ ] `PYTHONPATH=. pytest tests/test_section_detector.py tests/test_list_sections.py` passes.
- [ ] Existing suites (`test_rlm_workflow.py`, navigation, corpus management) still pass, ensuring section wiring did not break context snapshots.
- [ ] Manual smoke: load a Markdown file with `#` headings, run `list_sections`, and confirm the offsets/levels align with the source text.

---

#### Step 12: Add SQLite-backed persistent storage
- [ ] Create `storage.py` implementing the storage strategy interface, SQLite backend, and factory:

```python
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
    """Strategy interface for corpus persistence layers."""

    @abstractmethod
    def save_corpus(self, corpus: Corpus) -> None:
        """Persist the complete corpus (documents + chunks + metadata)."""

    @abstractmethod
    def load_corpus(self, corpus_id: str) -> Optional[Corpus]:
        """Load a corpus snapshot by id, returning ``None`` if it does not exist."""

    @abstractmethod
    def delete_corpus(self, corpus_id: str) -> bool:
        """Remove a corpus and its artifacts. Returns True when a row was deleted."""

    @abstractmethod
    def list_corpora(self) -> List[Dict[str, Any]]:
        """Return lightweight corpus metadata (id, name, counts)."""

    @abstractmethod
    def get_chunk(self, corpus_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Return a serialized chunk payload, or ``None`` if it cannot be found."""


class SQLiteStorage(StorageBackend):
    """SQLite-backed persistent store."""

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
    """Factory for instantiating the configured storage backend."""

    if backend == "sqlite":
        db_path = kwargs.get("db_path") or "rlm_corpus.db"
        return SQLiteStorage(db_path=db_path)
    raise ValueError(f"Unknown storage backend '{backend}'")
```

- [ ] Update `rlm_corpus_server.py` to instantiate and leverage the storage backend. Key changes include:

```python
from storage import StorageBackend, create_storage_backend

# Instantiate storage once, allowing environment overrides for db location.
STORAGE_BACKEND: StorageBackend = create_storage_backend(
    backend=os.getenv("RLM_STORAGE_BACKEND", "sqlite"),
    db_path=os.getenv(
        "RLM_STORAGE_PATH",
        str(Path(__file__).with_name("rlm_corpus.db")),
    ),
)


def _get_corpus_or_error(corpus_id: str) -> Corpus:
    corpus = corpora.get(corpus_id)
    if corpus:
        return corpus
    loaded = STORAGE_BACKEND.load_corpus(corpus_id)
    if loaded:
        corpora[corpus_id] = loaded
        return loaded
    raise ValueError(f"Corpus '{corpus_id}' does not exist")


@app.tool()
def load_corpus(...):
    ...
    corpora[corpus.corpus_id] = corpus
    STORAGE_BACKEND.save_corpus(corpus)
    return {...}


@app.tool()
def append_documents(...):
    ...
    corpus.documents.extend(new_documents)
    STORAGE_BACKEND.save_corpus(corpus)
    return {...}


@app.tool()
def list_corpus() -> Dict[str, Any]:
    return {"corpora": STORAGE_BACKEND.list_corpora()}


@app.tool()
def describe_corpus(...):
    corpus = _get_corpus_or_error(corpus_id)
    return {...}


@app.tool()
def delete_corpus(...):
    removed = STORAGE_BACKEND.delete_corpus(corpus_id)
    corpora.pop(corpus_id, None)
    return {...}


@app.tool()
def get_chunk(...):
    payload = STORAGE_BACKEND.get_chunk(corpus_id, chunk_id)
    if payload:
        return payload
    raise ValueError(...)
```

  The snippet above is illustrative—lift the exact `load_corpus`, `append_documents`, `list_corpus`, `describe_corpus`, `delete_corpus`, and `get_chunk` bodies from the current server, inserting the `STORAGE_BACKEND` calls where indicated. Ensure `Path` from `pathlib` remains imported near the top so the database path resolves correctly.
- [ ] Add `tests/test_storage.py` to exercise persistence semantics:

```python
from __future__ import annotations

from pathlib import Path

import pytest

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
```

- [ ] Export `STORAGE_BACKEND` via environment variables in `.env.example`/documentation if you maintain such files (optional but recommended) so operators can override the database location without editing code.

##### Step 12 Verification Checklist
- [ ] `PYTHONPATH=. pytest tests/test_storage.py tests/test_corpus_management_tools.py tests/test_navigation_tools.py` passes.
- [ ] Restarting the MCP server preserves previously loaded corpora (manual smoke test: load corpus, restart server, call `describe_corpus`).
- [ ] Setting `RLM_STORAGE_PATH=/tmp/rlm.db` stores data in the specified location.

#### Step 12 STOP & COMMIT
**STOP & COMMIT:** Stage `storage.py`, the updated server, and the new tests. Commit with a message like `feat(storage): add SQLite persistence backend` before moving to Step 13.

---

#### Step 13: Harden the REPL with RestrictedPython
- [ ] Append the dependency to `requirements.txt` and reinstall:

```text
RestrictedPython>=7.0
```

- [ ] Create `docs/security.md` describing the new sandbox guarantees, allowed modules (`math`, `re`, `json`), and how to extend the whitelist when absolutely necessary. Include quick guidance on why potentially dangerous modules (`os`, `subprocess`, `pathlib`) remain blocked.
- [ ] Update `rlm_corpus_server.py` so `REPLSession.execute` compiles code with RestrictedPython instead of the raw `exec`. Add a helper that builds the sandbox globals with a curated importer:

```python
from RestrictedPython import compile_restricted, safe_builtins
from RestrictedPython.Eval import default_guarded_getiter
from RestrictedPython.Guards import guarded_iter_unpack_sequence, guarded_unpack_sequence, safer_getattr
from RestrictedPython.PrintCollector import PrintCollector

SAFE_MODULES = {"math", "re", "json"}


def _limited_import(name: str, globals_dict=None, locals_dict=None, fromlist=(), level=0):
    if name in SAFE_MODULES:
        return __import__(name, globals_dict, locals_dict, fromlist, level)
    raise ImportError(f"Import of '{name}' is not permitted in the sandbox")


class REPLSession:
    ...

    def _build_sandbox_globals(self) -> Dict[str, Any]:
        allowed_builtins = dict(safe_builtins)
        allowed_builtins["__import__"] = _limited_import

        sandbox_globals: Dict[str, Any] = {
            "__builtins__": allowed_builtins,
            "_print_": PrintCollector,
            "_getiter_": default_guarded_getiter,
            "_getitem_": lambda obj, key: obj[key],
            "_getattr_": safer_getattr,
            "_iter_unpack_": guarded_iter_unpack_sequence,
            "_unpack_sequence_": guarded_unpack_sequence,
            "context": self.context,
            "context_meta": self.context_meta,
        }
        # Pre-import the whitelisted modules so user code can `import math` safely.
        for module_name in SAFE_MODULES:
            sandbox_globals[module_name] = __import__(module_name)
        sandbox_globals["llm_query"] = self.namespace.get("llm_query", self._default_llm_query)
        return sandbox_globals

    def execute(...):
        capture_variables = capture_variables or []
        stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()

    ##### Sandbox whitelist
    - Default whitelisted modules (`SAFE_MODULES`): `math`, `re`, `json`.
    - Additional safe builtins layered on top of `safe_builtins`: `enumerate`, `range`, `len`, `sum`, `min`, `max`, `sorted`, `zip`, `map`, `filter`, `any`, `all`, `print`.
    - `_limited_import` enforces the whitelist by raising `ImportError` for any other module name; extend this list cautiously when new helpers are required.

#### Enabling RestrictedPython (opt-in)

The RestrictedPython sandbox implemented above is intentionally opt-in so that regular development and tests remain ergonomic.

- To enable the sandbox at runtime, set the environment variable `RLM_USE_RESTRICTED_PYTHON=1` before starting the server or running test runs that should exercise the sandbox. Example (POSIX):

```bash
export RLM_USE_RESTRICTED_PYTHON=1
python rlm_corpus_server.py
```

- Run tests under the sandbox to validate behavior:

```bash
export RLM_USE_RESTRICTED_PYTHON=1
pytest -q
```

- Notes:
    - `RestrictedPython` must be installed (see `requirements.txt`).
    - The sandbox limits imports and builtins — expand `SAFE_MODULES` and allowed helpers in `_build_sandbox_globals` as needed and with care.
        stderr_buffer = io.StringIO()
        try:
            code_obj = compile_restricted(code, filename="<rlm-repl>", mode="exec")
        except Exception as exc:
            stderr_buffer.write(f"Compilation failed: {exc}\n")
            return {
                "stdout": "",
                "stderr": stderr_buffer.getvalue(),
                "truncated": False,
                "exports": {},
                "usage": {"exec_count": self.exec_count, "last_activity_at": self.last_activity_at.isoformat()},
            }

        sandbox_globals = self._build_sandbox_globals()
        sandbox_locals = self.namespace
        sandbox_locals["context"] = self.context
        sandbox_locals["context_meta"] = self.context_meta
        sandbox_locals["llm_query"] = sandbox_globals["llm_query"]

        try:
            sys.stdout, sys.stderr = stdout_buffer, stderr_buffer
            exec(code_obj, sandbox_globals, sandbox_locals)
        except Exception:
            traceback.print_exc(file=stderr_buffer)
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
```

  The helper above keeps `context`, `context_meta`, and (optionally) `llm_query` available while preventing arbitrary imports or filesystem access.
- [ ] Add `tests/test_restricted_repl.py` to ensure the sandbox both permits safe operations and blocks dangerous ones:

```python
from __future__ import annotations

import pytest

import rlm_corpus_server as server


def _session():
    corpus = create_corpus(
        name="Test",
        documents=[{"text": "Jazz festivals explore improv."}],
        chunk_size_chars=64,
        chunk_overlap_chars=0,
    )
    snapshot = corpus_to_snapshot(corpus)
    return server.REPLSession(snapshot, context_view="by_chunk")


def test_allowed_math_module():
    session = _session()
    result = session.execute("import math\nvalue = math.sqrt(16)", capture_variables=["value"])
    assert result["stderr"] == ""
    assert result["exports"]["value"] == "4.0"


def test_import_os_is_blocked():
    session = _session()
    outcome = session.execute("import os\nos.listdir()", capture_variables=[])
    assert "Import\" of 'os'" in outcome["stderr"] or "ImportError" in outcome["stderr"]


def test_file_io_is_unavailable():
    session = _session()
    result = session.execute("open('README.md').read()", capture_variables=[])
    assert "NameError" in result["stderr"]
```

##### Step 13 Verification Checklist
- [ ] `pip install -r requirements.txt` succeeds on a clean virtual environment.
- [ ] `PYTHONPATH=. pytest tests/test_restricted_repl.py tests/test_rlm_workflow.py` passes.
- [ ] Manual smoke: run an `exec_repl` snippet that imports `re` (allowed) and confirm importing `os` now fails with an `ImportError` surfaced in the REPL output.

#### Step 13 STOP & COMMIT
**STOP & COMMIT:** Stage the requirements update, `docs/security.md`, test files, and `rlm_corpus_server.py`. Commit with a message like `feat(repl): sandbox REPL execution`.

---
