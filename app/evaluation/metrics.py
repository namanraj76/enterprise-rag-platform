from __future__ import annotations

from typing import Iterable, List


def recall_at_k(relevant_ids: Iterable[str], retrieved_ids: List[str], k: int = 5) -> float:
    retrieved_slice = retrieved_ids[:k]
    relevant_set = set(relevant_ids)
    if not relevant_set:
        return 1.0
    return float(len(relevant_set.intersection(retrieved_slice)) / len(relevant_set))


def mean_reciprocal_rank(relevant_ids: Iterable[str], retrieved_ids: List[str]) -> float:
    relevant_set = set(relevant_ids)
    for idx, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant_set:
            return 1.0 / idx
    return 0.0
