from __future__ import annotations

from typing import List

from app.core.models import Chunk, RetrievalResult
from app.retrieval.bm25 import BM25Retriever
from app.retrieval.reranker import SimpleReranker
from app.retrieval.semantic import SemanticRetriever


class HybridRetriever:
    """Coordinates semantic and lexical retrieval into a hybrid ranking pipeline."""

    def __init__(self, chunks: List[Chunk]):
        self.chunks = chunks
        self.semantic_retriever = SemanticRetriever(chunks)
        self.bm25_retriever = BM25Retriever(chunks)
        self.reranker = SimpleReranker()

    def search(self, query: str, top_k: int = 5) -> List[RetrievalResult]:
        semantic_results = self.semantic_retriever.search(query, top_k=max(top_k * 3, 10))
        lexical_results = self.bm25_retriever.search(query, top_k=max(top_k * 3, 10))
        reranked = self.reranker.rerank(semantic_results, lexical_results)
        return reranked[:top_k]
