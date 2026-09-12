from __future__ import annotations

from typing import List

from app.core.models import Chunk, SourceDocument


class SimpleChunker:
    """Splits text into focused chunks while preserving section context."""

    def __init__(self, chunk_size: int = 400, overlap: int = 60):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: SourceDocument) -> List[Chunk]:
        text = document.content.strip()
        if not text:
            return []

        chunks: List[Chunk] = []
        start = 0
        index = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            segment = text[start:end]
            if end < len(text):
                segment = segment.rstrip()
            chunk_id = f"{document.doc_id}_chunk_{index}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=document.doc_id,
                    text=segment,
                    source=document.source,
                    section=document.section,
                    version=document.version,
                    metadata={**document.metadata, "title": document.title},
                )
            )
            index += 1
            start = max(0, end - self.overlap)
        return chunks
