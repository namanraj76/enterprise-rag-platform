# Enterprise RAG & Knowledge Intelligence Platform

A practical enterprise retrieval-augmented generation project designed around the full request flow described in the study guide: document ingestion, metadata enrichment, chunking, embeddings, hybrid retrieval, reranking, grounded generation, evaluation, API exposure, and deployment-ready packaging.

![CI](https://github.com/namanraj76/enterprise-rag-platform/actions/workflows/ci.yml/badge.svg)

## Goals

- Build a RAG platform that answers questions from internal knowledge sources.
- Separate offline indexing from online querying.
- Keep architecture explainable and interview-ready.
- Provide a working project structure that can be pushed to GitHub and extended.

## Project structure

```text
enterprise-rag-platform/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   └── main.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── models.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── document_loader.py
│   │   ├── chunker.py
│   │   └── metadata.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── hybrid.py
│   │   ├── bm25.py
│   │   ├── semantic.py
│   │   └── reranker.py
│   ├── generation/
│   │   ├── __init__.py
│   │   ├── grounded_generator.py
│   │   └── prompt.py
│   ├── evaluation/
│   │   ├── __init__.py
│   │   └── metrics.py
│   └── utils/
│       ├── __init__.py
│       └── logging.py
├── data/
│   └── sample_documents/
├── tests/
│   ├── test_pipeline.py
│   └── test_api.py
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
├── pytest.ini
├── run.py
└── README.md
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

CI: This repository includes a GitHub Actions workflow that runs the test suite on push and pull requests. The workflow runs `pytest -q` on Python 3.12.

Then open the FastAPI docs at:

- http://localhost:8000/docs
- http://localhost:8000/redoc

## Notes

This project intentionally uses a simple local in-memory implementation for the indexing and retrieval layers so it can run without external services. The architecture is structured to allow extension to real vector databases, embedding models, a proper BM25 index, and an enterprise-grade observability stack later.
