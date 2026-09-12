from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.models import Answer
from app.generation.grounded_generator import GroundedGenerator
from app.ingestion.chunker import SimpleChunker
from app.ingestion.document_loader import DocumentLoader
from app.retrieval.hybrid import HybridRetriever

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

    documents = DocumentLoader(DATA_DIR).load()
    if not documents:
        raise HTTPException(status_code=404, detail="No documents were found in the sample data directory")

    chunker = SimpleChunker()
    all_chunks = []
    for document in documents:
        all_chunks.extend(chunker.chunk(document))

    if not all_chunks:
        raise HTTPException(status_code=404, detail="No chunks were generated from the sample documents")

    retriever = HybridRetriever(all_chunks)
    evidence = retriever.search(payload.question, top_k=payload.top_k)
    generator = GroundedGenerator()
    answer = generator.generate(payload.question, evidence)

    return QueryResponse(
        answer=answer.answer,
        citations=answer.citations,
        evidence=[item.text for item in answer.evidence],
    )
