from __future__ import annotations

from typing import List

from rank_bm25 import BM25Okapi
from app.utils.logging import logger
import time

from app.core.models import Chunk, RetrievalResult


class BM25Retriever:
    """Lexical retrieval based on BM25 scoring."""

    def __init__(self, documents: List[Chunk]):
        self.documents = documents
        self.tokenized_docs = [doc.text.lower().split() for doc in documents]
        self.index = BM25Okapi(self.tokenized_docs) if self.tokenized_docs else None

    def search(self, query: str, top_k: int = 5) -> List[RetrievalResult]:
        t0 = time.perf_counter()
        if not self.documents or self.index is None:
            logger.info("bm25 search: no index/documents")
            return []

        scores = self.index.get_scores(query.lower().split())
        t1 = time.perf_counter()
        logger.info("bm25 scoring duration=%.3fs", t1 - t0)
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results: List[RetrievalResult] = []
        for idx in ranked_indices:
            chunk = self.documents[idx]
            results.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    source=chunk.source,
                    section=chunk.section,
                    version=chunk.version,
                    score=float(scores[idx]),
                    metadata=chunk.metadata,
                )
            )
        return results
