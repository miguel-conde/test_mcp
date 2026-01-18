# Conversation Corpus: Operational Constraints (No Summaries)

This document captures practical constraints and required operating patterns when storing the full raw conversation (user + assistant messages) in a Conversation Corpus and optionally mining it via a Conversation REPL Session.

## 1. Conceptual capability
- If the full transcript is stored in a Conversation Corpus, the agent can mine it in two ways:
  - Targeted retrieval with `search_corpus` (fast narrowing / lookup)
  - Programmable mining with a Conversation REPL Session (`open_session` + `exec_repl`) where the corpus is available as `context`

## 2. Practical limits (cost/latency)
- “Mining the entire conversation” means iterating across all `context` items (documents/chunks). As the chat grows, this becomes increasingly slow and can be costly.
- Recommended pattern:
  - Use `search_corpus` first to narrow to relevant turns.
  - Then use `exec_repl` on the narrowed set (or on the full `context` only when truly necessary).

## 3. Snapshot-based sessions (correctness constraint)
- The current server design builds REPL sessions from a snapshot of a corpus at `open_session` time.
- Therefore, if you append new turns to the Conversation Corpus, an already-open Conversation REPL Session will NOT automatically see them.

### Required refresh workflow
After `append_documents`:
1. `close_session(session_id)`
2. `open_session(corpus_id=<conversation_corpus_id>, ...)`

If you skip this, any REPL mining will run against an older snapshot (missing the newest appended messages).

## 4. What this means for “always available and complete context”
- The Conversation Corpus can contain the complete raw transcript and is the source of truth.
- The Conversation REPL Session is optional compute; to keep it “current”, you must reopen it after appends.
- Even with complete storage, full linear scans should be treated as a last resort due to scaling costs.
