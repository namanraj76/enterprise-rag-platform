from app.ingestion.chunker import SimpleChunker
from app.ingestion.document_loader import DocumentLoader
from app.retrieval.hybrid import HybridRetriever


def test_document_loader_reads_sample_documents():
    docs = DocumentLoader("data/sample_documents").load()
    assert len(docs) >= 2
    assert all(doc.content.strip() for doc in docs)


def test_chunker_creates_chunks():
    docs = DocumentLoader("data/sample_documents").load()
    chunker = SimpleChunker(chunk_size=200, overlap=20)
    chunks = []
    for doc in docs:
        chunks.extend(chunker.chunk(doc))
    assert len(chunks) > 0
    assert all(chunk.text for chunk in chunks)


def test_hybrid_retriever_returns_candidates():
    docs = DocumentLoader("data/sample_documents").load()
    chunks = []
    for doc in docs:
        chunks.extend(SimpleChunker(chunk_size=200, overlap=20).chunk(doc))

    retriever = HybridRetriever(chunks)
    results = retriever.search("AUTH-401 after upgrading the gateway")
    assert len(results) > 0
    assert all(item.text for item in results)
