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
    """Return the top chunk matches for a literal query.

    Results are dictionaries containing `chunk_id`, `document_id`,
    `section_id`, `score` and a short `snippet` showing the match.
    """
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
