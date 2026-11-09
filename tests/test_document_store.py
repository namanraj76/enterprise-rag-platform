from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document

import app.ingestion.document_store as store_module
from app.ingestion.document_store import (
    DocumentIngestionError,
    LocalDocumentStore,
    extract_document,
)


def test_txt_ingestion_chunks_and_retrieves_citations():
    store = LocalDocumentStore()
    info = store.add(
        "../security.txt",
        ("Rotate access keys every 90 days. " * 500).encode("utf-8"),
    )

    assert info.filename == "security.txt"
    assert info.chunks > 1
    evidence = store.search("How often rotate access keys?")
    assert evidence
    assert evidence[0].citation.startswith("security.txt, document, chunk")
    assert "Rotate access keys" in evidence[0].text
    assert store.search("the and or") == []
    assert store.remove(info.document_id)
    assert store.search("access keys") == []


def test_hindi_text_can_be_retrieved_with_hindi_queries():
    store = LocalDocumentStore()
    store.add(
        "ai-notes.txt",
        "कृत्रिम बुद्धिमत्ता डेटा से पैटर्न सीखकर निर्णय लेने में मदद करती है।".encode("utf-8"),
    )

    evidence = store.search("कृत्रिम बुद्धिमत्ता क्या है")

    assert evidence
    assert evidence[0].filename == "ai-notes.txt"
    assert "डेटा से पैटर्न सीखकर" in evidence[0].text


def test_docx_extraction_includes_paragraphs_and_table_content():
    document = Document()
    document.add_paragraph("Password rotation guidance")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Rotate every"
    table.cell(0, 1).text = "90 days"
    payload = BytesIO()
    document.save(payload)

    sections = extract_document("policy.docx", payload.getvalue())

    assert sections[0][0] == "document"
    assert "Password rotation guidance" in sections[0][1]
    assert "Rotate every | 90 days" in sections[0][1]


def test_pdf_extraction_retains_page_citations(monkeypatch):
    class Reader:
        is_encrypted = False
        pages = [
            SimpleNamespace(extract_text=lambda: "First page evidence"),
            SimpleNamespace(extract_text=lambda: "Second page evidence"),
        ]

    monkeypatch.setattr(store_module, "PdfReader", lambda *args, **kwargs: Reader())

    assert extract_document("guide.pdf", b"%PDF-1.7 test") == [
        ("page 1", "First page evidence"),
        ("page 2", "Second page evidence"),
    ]


@pytest.mark.parametrize(
    ("filename", "payload", "message"),
    [
        ("wrong.pdf", b"plain text", "not a valid PDF"),
        ("wrong.docx", b"not a zip archive", "not a valid DOCX"),
        ("bad.txt", b"\xff", "UTF-8"),
        ("empty.txt", b"   ", "No readable text"),
    ],
)
def test_invalid_or_unreadable_documents_raise_clear_errors(filename, payload, message):
    if filename == "empty.txt":
        store = LocalDocumentStore()
        with pytest.raises(DocumentIngestionError, match=message):
            store.add(filename, payload)
    else:
        with pytest.raises(DocumentIngestionError, match=message):
            extract_document(filename, payload)
