from __future__ import annotations

from typing import List

from app.core.models import Chunk, SourceDocument
from app.utils.logging import logger
import time


class SimpleChunker:
    """Splits text into focused chunks while preserving section context."""

    def __init__(self, chunk_size: int = 400, overlap: int = 60):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: SourceDocument) -> List[Chunk]:
        t0 = time.perf_counter()
        logger.info("chunker: start doc_id=%s title=%s", document.doc_id, document.title)
        text = document.content.strip()
        if not text:
            logger.info("chunker: empty document doc_id=%s", document.doc_id)
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
            # If we've reached the end of the text, stop. Otherwise advance by chunk_size - overlap.
            if end >= len(text):
                break
            start = max(0, end - self.overlap)
        t1 = time.perf_counter()
        logger.info("chunker: finished doc_id=%s chunks=%d duration=%.3fs", document.doc_id, len(chunks), t1 - t0)
        return chunks
