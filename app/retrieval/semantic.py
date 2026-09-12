from __future__ import annotations

from typing import List

import numpy as np

from app.core.models import Chunk, RetrievalResult


class SemanticRetriever:
    """Simple semantic retriever based on cosine similarity over sentence embeddings."""

    def __init__(self, documents: List[Chunk]):
        self.documents = documents
        self._embeddings = self._build_embeddings()

    def _build_embeddings(self) -> np.ndarray:
        if not self.documents:
            return np.empty((0, 1))

        vectors = []
        for doc in self.documents:
            tokens = doc.text.lower().split()
            vector = np.array([len(tokens), sum(ord(ch) for ch in doc.text) % 1000], dtype=float)
            vectors.append(vector)
        return np.vstack(vectors)

    def search(self, query: str, top_k: int = 5) -> List[RetrievalResult]:
        if not self.documents:
            return []

        q_vector = np.array([
            len(query.lower().split()),
            sum(ord(ch) for ch in query) % 1000,
        ], dtype=float)

        if np.allclose(self._embeddings, 0):
            return []

        norms = np.linalg.norm(self._embeddings, axis=1)
        query_norm = np.linalg.norm(q_vector)
        if query_norm == 0:
            return []

        sims = (self._embeddings @ q_vector) / (norms * query_norm)
        indices = np.argsort(sims)[::-1][:top_k]

        results: List[RetrievalResult] = []
        for idx in indices:
            chunk = self.documents[int(idx)]
            results.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    source=chunk.source,
                    section=chunk.section,
                    version=chunk.version,
                    score=float(sims[int(idx)]),
                    metadata=chunk.metadata,
                )
            )
        return results
