# Experimental: `llm_query` OpenAI integration

This document explains the experimental OpenAI-backed `llm_query` behavior for `rlm_corpus_server`.

When `open_session(..., enable_llm_query=True)` is called, the server will expose a callable `llm_query(prompt: str)` inside the REPL that performs an API call to OpenAI.

Important notes
- Costs: each call incurs API charges. Use sparingly during experiments.
- Safety: the REPL catches and returns API errors as strings (prefixed with `ERROR:`) rather than throwing.
- Default behavior: `enable_llm_query=False` keeps the existing stub and requires no API key.

Configuration
- Set `OPENAI_API_KEY` in the environment or in the `env` section of your `mcp.json`.

Testing
- Tests should mock the OpenAI client; the repo includes a test scaffold to demonstrate mocking instead of performing real network calls.
