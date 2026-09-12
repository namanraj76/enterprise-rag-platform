from __future__ import annotations

from typing import List

from app.core.models import RetrievalResult


class SimpleReranker:
    """Combines lexical and semantic scores with a simple weighted re-ranking."""

    def rerank(self, semantic: List[RetrievalResult], lexical: List[RetrievalResult], alpha: float = 0.6) -> List[RetrievalResult]:
        merged = {}
        for result in semantic:
            merged[result.chunk_id] = {"result": result, "semantic": result.score, "lexical": 0.0}
        for result in lexical:
            if result.chunk_id in merged:
                merged[result.chunk_id]["lexical"] = result.score
            else:
                merged[result.chunk_id] = {"result": result, "semantic": 0.0, "lexical": result.score}

        ranked = []
        for item in merged.values():
            combined = alpha * item["semantic"] + (1 - alpha) * item["lexical"]
            result = item["result"]
            result.score = combined
            ranked.append(result)

        return sorted(ranked, key=lambda r: r.score, reverse=True)
