from __future__ import annotations

from typing import List

from app.core.models import Answer, RetrievalResult
from app.generation.prompt import build_prompt
from app.utils.logging import logger
import time


class GroundedGenerator:
    """Produces grounded responses using retrieved evidence rather than raw model memory."""

    def generate(self, question: str, evidence: List[RetrievalResult]) -> Answer:
        t0 = time.perf_counter()
        if not evidence:
            return Answer(
                answer="I could not find evidence in the indexed knowledge base that supports an answer to that question.",
                citations=[],
                evidence=[],
                validation={"status": "no_evidence_found"},
            )

        evidence_text = "\n\n".join(
            f"[chunk_id={item.chunk_id}] {item.text}"
            for item in evidence
        )

        prompt = build_prompt(question, evidence_text)
        answer_text = self._simulate_answer(question, evidence)
        t1 = time.perf_counter()
        logger.info("grounded generation: evidence=%d prompt_len=%d duration=%.3fs", len(evidence), len(prompt), t1 - t0)
        citations = [item.chunk_id for item in evidence]

        return Answer(
            answer=answer_text,
            citations=citations,
            evidence=evidence,
            validation={"status": "grounded", "prompt_length": len(prompt)},
        )

    def _simulate_answer(self, question: str, evidence: List[RetrievalResult]) -> str:
        sources = ", ".join(item.chunk_id for item in evidence[:2])
        if not question:
            return "Please provide a question to search the knowledge base."
        first_text = evidence[0].text
        return (
            f"Based on the retrieved evidence ({sources}), the most relevant source indicates: "
            f"{first_text[:220]}"
        )
