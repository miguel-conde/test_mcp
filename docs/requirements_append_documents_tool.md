# Requirements: `append_documents` MCP Tool (RLM Corpus Server)

## 1. Summary
Add a new MCP tool to the existing `rlm-corpus-server` that allows **incrementally appending new documents** to an already-loaded corpus.

Primary use case: persist the full, raw chat transcript (user + assistant turns) in a “conversation corpus” without recreating the corpus every turn.

## 2. Context (current design constraints)
- Corpora are stored in-memory in the server-wide registry (`corpora: dict[corpus_id, Corpus]`).
- `open_session(...)` creates a `REPLSession` from a **snapshot** (`corpus_to_snapshot(corpus)`), and the REPL session materializes `context`/`context_meta` from that snapshot.
- Therefore, appended documents will **not** automatically appear in an already-open session unless the client:
  - closes and reopens the session, or
  - a future “refresh session” capability is added.

This tool focuses only on corpus mutation (append), not session refresh.

## 3. Goals / Non-goals

### Goals
- Append one or more documents to an existing corpus, reusing the server’s current chunking strategy and data model (`Corpus` → `Document` → `Chunk`).
- Preserve compatibility with existing tools:
  - `search_corpus`, `get_chunk`, `list_chunks`, and `describe_corpus` must work over appended content.
- Provide predictable behavior and clear error messages for invalid input.

### Non-goals (explicit)
- No summarization or transformation of text (raw text is stored as provided).
- No updating/replacing existing documents (append-only).
- No automatic refresh of existing REPL sessions.
- No persistence across server restarts (still in-memory only).

## 4. Tool name
- **Name:** `append_documents`
- **Namespace:** `rlm-corpus-server/append_documents` (consistent with existing server tools)

## 5. Functional requirements

### FR1 — Append documents
The tool MUST append documents to an existing corpus identified by `corpus_id`.

### FR2 — Input normalization
The tool MUST accept documents in the same shape as `load_corpus` currently supports:
- Each item must include:
  - `text: string` (non-empty after stripping)
  - `document_name: string` OR `name: string` (fallback to an auto-generated name if missing)

### FR3 — Chunking
For each appended document, the server MUST chunk its text using the corpus’s configured:
- `chunk_size_chars`
- `chunk_overlap_chars`

Chunk IDs MUST be unique (reuse current UUID-based generation).

### FR4 — Metadata updates
After appending:
- `Corpus.documents` MUST include the new `Document` objects.
- Each `Document.meta["num_chunks"]` MUST reflect its chunk count.
- `describe_corpus(..., include_documents=True)` MUST reflect the updated counts.

### FR5 — No modification to existing documents
The tool MUST NOT alter existing `Document` or `Chunk` objects.

### FR6 — Deterministic error behavior
The tool MUST:
- fail fast for invalid `corpus_id` or invalid documents
- not partially append when validation fails (atomic behavior; see Section 8)

## 6. API contract

### 6.1 Input schema (JSON-schema-like)
```json
{
  "type": "object",
  "properties": {
    "corpus_id": {"type": "string"},
    "documents": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "document_name": {"type": "string"},
          "name": {"type": "string"},
          "text": {"type": "string"},
          "meta": {"type": "object"}
        },
        "required": ["text"]
      }
    }
  },
  "required": ["corpus_id", "documents"]
}
```

### 6.2 Output schema
```json
{
  "corpus_id": "string",
  "num_documents_before": 0,
  "num_documents_after": 0,
  "num_chunks_before": 0,
  "num_chunks_after": 0,
  "added": {
    "num_documents": 0,
    "num_chunks": 0
  },
  "documents": [
    {
      "document_id": "string",
      "document_name": "string",
      "num_chunks": 0
    }
  ]
}
```

Notes:
- The returned `documents` list MUST correspond only to the newly appended documents.

## 7. Behavioral specification

### 7.1 Corpus lookup
- If `corpus_id` does not exist: raise `ValueError("Corpus '{corpus_id}' does not exist")` (consistent with current patterns).

### 7.2 Document validation
For each document in `documents`:
- `text` MUST be a string and MUST contain non-whitespace characters.
- `document_name` is resolved as:
  1. `document["document_name"]` if present and non-empty
  2. else `document["name"]` if present and non-empty
  3. else `"document-{n}"` (1-based index in the append request)

If any document is invalid, the tool MUST fail and MUST NOT append any documents.

### 7.3 Atomic append
Implementation MUST be atomic at the tool-call level:
- Validate all documents first.
- Then create `Document`/`Chunk` objects in memory.
- Only after all are successfully created, extend `corpus.documents`.

### 7.4 Session interaction (important)
- Existing REPL sessions are built from snapshots.
- Appending documents does NOT mutate existing session snapshots.
- Clients MUST close/reopen sessions to see new content.
- The server MUST NOT attempt to auto-update existing `REPLSession` instances.

### 7.5 Limits
- The tool MAY enforce a per-call document limit (e.g., max 100 documents) to avoid abuse.
- If added, limits MUST be documented in the tool description and surfaced via clear errors.

## 8. Error handling requirements

- Missing corpus:
  - `ValueError("Corpus '{corpus_id}' does not exist")`
- Empty `documents` array:
  - `ValueError("documents must be a non-empty list")` (or equivalent)
- Invalid doc text:
  - `ValueError("Document #{i} is missing text")` (consistent with current `_normalize_documents` messaging)

No partial success responses.

## 9. Security / safety

- No file I/O.
- No network operations.
- Text is treated as opaque data; do not attempt to parse or execute it.
- Continue to rely on the current REPL safeguards (server-controlled reinjection of `context/context_meta/llm_query`).

## 10. Testing requirements

### Unit tests (pytest)
Add tests under `tests/` verifying:
1. **Happy path**: append 2 documents; `describe_corpus` shows increased `num_documents` and `num_chunks`.
2. **Search integration**: appended content becomes searchable via `search_corpus`.
3. **Chunk retrieval**: `get_chunk` can fetch a chunk belonging to an appended document.
4. **Atomicity**: when one of the appended documents is invalid, nothing is appended.
5. **Session snapshot behavior** (contract test):
   - open session, append documents, verify the existing session context does not change
   - reopen session, verify new content is visible

## 11. Example flow (conversation transcript)

1. Create a conversation corpus:
   - `load_corpus(name="Conversation Transcript", documents=[turn-001, turn-002])`
2. On every new turn, append 1–2 new documents:
   - `append_documents(corpus_id=..., documents=[turn-003-user, turn-004-assistant])`
3. If using REPL over the conversation corpus:
   - `close_session(old_session_id)`
   - `open_session(corpus_id=..., context_view="by_document")`

## 12. Future extension (optional, not in scope)
If desired later, add `refresh_session(session_id)` to rematerialize `context/context_meta` from the current corpus without reopening.
