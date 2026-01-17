from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
        created_at=datetime.now(timezone.utc),
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
    documents: List[Dict[str, Any]] = []
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
