from __future__ import annotations

from typing import List

from app.core.models import Chunk, RetrievalResult
from app.retrieval.bm25 import BM25Retriever
from app.retrieval.reranker import SimpleReranker
from app.retrieval.semantic import SemanticRetriever
from app.utils.logging import logger
import time


class HybridRetriever:
    """Coordinates semantic and lexical retrieval into a hybrid ranking pipeline."""

    def __init__(self, chunks: List[Chunk]):
        self.chunks = chunks
        self.semantic_retriever = SemanticRetriever(chunks)
        self.bm25_retriever = BM25Retriever(chunks)
        self.reranker = SimpleReranker()

    def search(self, query: str, top_k: int = 5) -> List[RetrievalResult]:
        t0 = time.perf_counter()
        semantic_results = self.semantic_retriever.search(query, top_k=max(top_k * 3, 10))
        t1 = time.perf_counter()
        logger.info("semantic search: returned=%d duration=%.3fs", len(semantic_results), t1 - t0)

        t0 = time.perf_counter()
        lexical_results = self.bm25_retriever.search(query, top_k=max(top_k * 3, 10))
        t1 = time.perf_counter()
        logger.info("bm25 search: returned=%d duration=%.3fs", len(lexical_results), t1 - t0)

        t0 = time.perf_counter()
        reranked = self.reranker.rerank(semantic_results, lexical_results)
        t1 = time.perf_counter()
        logger.info("rerank: returned=%d duration=%.3fs", len(reranked), t1 - t0)

        return reranked[:top_k]
