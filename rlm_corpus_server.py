from __future__ import annotations

import io
import json
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, TYPE_CHECKING, cast
from uuid import uuid4

if TYPE_CHECKING:  # pragma: no cover - only for type checking
    from mcp.server.fastmcp import FastMCP  # type: ignore

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - tests don't need MCP server to run
    class FastMCP:  # type: ignore
        def __init__(self, *args: object, **kwargs: object) -> None:
            """Runtime fallback used when `mcp` is not installed."""

        def run(self, *args: object, **kwargs: object) -> None:  # pragma: no cover - fallback
            return None

CorpusSnapshot = Dict[str, Any]
ContextTuple = Tuple[Any, Any]

SUPPORTED_CONTEXT_VIEWS = {"raw_text", "by_document", "by_chunk"}

app: FastMCP = FastMCP("rlm-corpus-server")

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


if __name__ == "__main__":
    app.run()
