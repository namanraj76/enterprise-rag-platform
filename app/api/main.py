from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.models import Answer
from app.generation.grounded_generator import GroundedGenerator
from app.ingestion.chunker import SimpleChunker
from app.ingestion.document_loader import DocumentLoader
from app.retrieval.hybrid import HybridRetriever
from app.utils.logging import logger
import time

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "sample_documents"

app = FastAPI(title="Enterprise RAG Platform")


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


class QueryResponse(BaseModel):
    answer: str
    citations: list[str]
    evidence: list[str]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "enterprise-rag-platform"}


@app.post("/query", response_model=QueryResponse)
def query_documents(payload: QueryRequest) -> QueryResponse:
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    start_total = time.perf_counter()
    logger.info("/query start: question=%s top_k=%s", payload.question, payload.top_k)

    t0 = time.perf_counter()
    documents = DocumentLoader(DATA_DIR).load()
    t1 = time.perf_counter()
    logger.info("document load: count=%d duration=%.3fs", len(documents) if documents else 0, t1 - t0)
    if not documents:
        raise HTTPException(status_code=404, detail="No documents were found in the sample data directory")

    t0 = time.perf_counter()
    chunker = SimpleChunker()
    all_chunks = []
    for document in documents:
        all_chunks.extend(chunker.chunk(document))
    t1 = time.perf_counter()
    logger.info("chunking: chunks=%d duration=%.3fs", len(all_chunks), t1 - t0)

    if not all_chunks:
        raise HTTPException(status_code=404, detail="No chunks were generated from the sample documents")

    t0 = time.perf_counter()
    retriever = HybridRetriever(all_chunks)
    evidence = retriever.search(payload.question, top_k=payload.top_k)
    t1 = time.perf_counter()
    logger.info("retrieval: candidates=%d duration=%.3fs", len(evidence) if evidence else 0, t1 - t0)

    t0 = time.perf_counter()
    generator = GroundedGenerator()
    answer = generator.generate(payload.question, evidence)
    t1 = time.perf_counter()
    logger.info("generation: duration=%.3fs", t1 - t0)

    end_total = time.perf_counter()
    logger.info("/query done: total_duration=%.3fs", end_total - start_total)

    return QueryResponse(
        answer=answer.answer,
        citations=answer.citations,
        evidence=[item.text for item in answer.evidence],
    )
