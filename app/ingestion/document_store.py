from __future__ import annotations

import io
import math
import re
import threading
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePath
import uuid

from docx import Document
from pypdf import PdfReader
from sqlalchemy import select

from app.core.database import SessionLocal, StoredChunk, StoredDocument

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARS = 2_000_000
CHUNK_WORDS = 300
CHUNK_OVERLAP_WORDS = 50
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}
TOKEN_RE = re.compile(r"[^\W_][\w'-]*", re.IGNORECASE)
QUERY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "did", "do", "does",
    "for", "from", "how", "i", "in", "is", "it", "me", "of", "on", "or", "the",
    "to", "was", "what", "when", "where", "which", "who", "why", "with", "would",
}


class DocumentIngestionError(ValueError):
    """Raised when an uploaded document cannot be safely ingested."""


@dataclass(frozen=True)
class DocumentInfo:
    document_id: str
    filename: str
    chunks: int


@dataclass(frozen=True)
class Evidence:
    citation: str
    text: str
    score: float
    filename: str
    page: int | None


@dataclass
class _Chunk:
    citation: str
    text: str
    tokens: list[str] = field(default_factory=list)
    filename: str = ""
    page: int | None = None


@dataclass
class _Document:
    info: DocumentInfo
    chunks: list[_Chunk]


def _extract_pdf(payload: bytes) -> list[tuple[str, str]]:
    if not payload.startswith(b"%PDF-"):
        raise DocumentIngestionError("The uploaded file is not a valid PDF.")
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise DocumentIngestionError("Password-protected PDFs are not supported.")
        if len(reader.pages) > 5000:
            raise DocumentIngestionError("PDF contains too many pages (maximum 5000).")
        pages = []
        total_chars = 0
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            total_chars += len(text)
            if total_chars > MAX_EXTRACTED_CHARS:
                raise DocumentIngestionError("Extracted document text exceeds the allowed limit.")
            if text.strip():
                pages.append((f"page {page_number}", text))
        return pages
    except DocumentIngestionError:
        raise
    except Exception as exc:
        raise DocumentIngestionError("Could not read the uploaded PDF.") from exc


def _extract_docx(payload: bytes) -> list[tuple[str, str]]:
    if not payload.startswith(b"PK"):
        raise DocumentIngestionError("The uploaded file is not a valid DOCX document.")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocumentIngestionError("The uploaded DOCX is missing required document data.")
            entries = archive.infolist()
            expanded_size = sum(entry.file_size for entry in entries)
            if len(entries) > 1000 or expanded_size > 50 * 1024 * 1024:
                raise DocumentIngestionError("DOCX archive expands beyond the allowed limit.")
            if any(entry.file_size > 1024 * 1024 and entry.compress_size == 0 for entry in entries):
                raise DocumentIngestionError("DOCX archive contains an invalid compressed entry.")
            if any(
                entry.compress_size and entry.file_size / entry.compress_size > 1000
                for entry in entries
            ):
                raise DocumentIngestionError("DOCX archive compression ratio is too high.")
        document = Document(io.BytesIO(payload))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                values = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if values:
                    paragraphs.append(" | ".join(values))
        text = "\n".join(paragraphs)
        if len(text) > MAX_EXTRACTED_CHARS:
            raise DocumentIngestionError("Extracted document text exceeds the allowed limit.")
        return [("document", text)] if text else []
    except DocumentIngestionError:
        raise
    except Exception as exc:
        raise DocumentIngestionError("Could not read the uploaded DOCX document.") from exc


def _extract_txt(payload: bytes) -> list[tuple[str, str]]:
    if b"\x00" in payload:
        raise DocumentIngestionError("TXT documents must contain UTF-8 text, not binary data.")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentIngestionError("TXT documents must be encoded as UTF-8.") from exc
    if len(text) > MAX_EXTRACTED_CHARS:
        raise DocumentIngestionError("Extracted document text exceeds the allowed limit.")
    return [("document", text)] if text.strip() else []


def extract_document(filename: str, payload: bytes) -> list[tuple[str, str]]:
    extension = PurePath(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentIngestionError("Unsupported file type. Upload a PDF, DOCX, or TXT file.")
    if not payload:
        raise DocumentIngestionError("The uploaded file is empty.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise DocumentIngestionError("File exceeds the 10 MiB upload limit.")
    if extension == ".pdf":
        return _extract_pdf(payload)
    if extension == ".docx":
        return _extract_docx(payload)
    return _extract_txt(payload)


def _chunk_text(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    step = CHUNK_WORDS - CHUNK_OVERLAP_WORDS
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + CHUNK_WORDS])
        if chunk:
            chunks.append(chunk)
        if start + CHUNK_WORDS >= len(words):
            break
    return chunks


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


class LocalDocumentStore:
    """Thread-safe in-memory document index; all parsing and retrieval run locally."""

    def __init__(self) -> None:
        self._documents: dict[str, _Document] = {}
        self._lock = threading.RLock()

    def add(self, filename: str, payload: bytes) -> DocumentInfo:
        # Keep only a display basename; uploaded paths are never used for filesystem access.
        raw_name = PurePath(filename.replace("\\", "/")).name.strip()
        display_name = "".join(character for character in raw_name if character.isprintable())[:200]
        if not display_name:
            raise DocumentIngestionError("A filename is required.")
        sections = extract_document(display_name, payload)
        document_id = uuid.uuid4().hex
        chunks = [
            _Chunk(
                citation=f"{display_name}, {location}, chunk {number}",
                text=chunk,
                tokens=_tokens(chunk),
                filename=display_name,
                page=int(location[5:]) if location.startswith("page ") else None,
            )
            for location, text in sections
            for number, chunk in enumerate(_chunk_text(text), start=1)
        ]
        if not chunks:
            raise DocumentIngestionError("No readable text was found in the document.")
        info = DocumentInfo(document_id=document_id, filename=display_name, chunks=len(chunks))
        with self._lock:
            self._documents[document_id] = _Document(info=info, chunks=chunks)
        return info

    def list_documents(self) -> list[DocumentInfo]:
        with self._lock:
            return [document.info for document in self._documents.values()]

    def remove(self, document_id: str) -> bool:
        with self._lock:
            return self._documents.pop(document_id, None) is not None

    def search(self, query: str, limit: int = 5) -> list[Evidence]:
        query_tokens = [token for token in _tokens(query) if token not in QUERY_STOPWORDS]
        query_terms = set(query_tokens)
        if not query_terms:
            return []
        with self._lock:
            chunks = [chunk for document in self._documents.values() for chunk in document.chunks]
        if not chunks:
            return []

        document_frequency = Counter(
            term for term in query_terms
            for chunk in chunks
            if term in set(chunk.tokens)
        )
        total_chunks = len(chunks)
        scored: list[Evidence] = []
        for chunk in chunks:
            term_counts = Counter(chunk.tokens)
            matched = query_terms.intersection(term_counts)
            coverage = len(matched) / len(query_terms)
            if not matched or coverage < 0.2:
                continue
            score = 0.0
            for term in matched:
                inverse_frequency = math.log(1 + (total_chunks - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                frequency = term_counts[term]
                score += inverse_frequency * (frequency * 2.2) / (frequency + 1.2)
            scored.append(
                Evidence(
                    citation=chunk.citation,
                    text=chunk.text,
                    score=score * coverage,
                    filename=chunk.filename,
                    page=chunk.page,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]


document_store = LocalDocumentStore()


class PersistentDocumentStore:
    """Database-backed document index with every read constrained by owner ID."""

    def add(self, user_id: str, filename: str, payload: bytes) -> DocumentInfo:
        raw_name = PurePath(filename.replace("\\", "/")).name.strip()
        display_name = "".join(character for character in raw_name if character.isprintable())[:200]
        if not display_name:
            raise DocumentIngestionError("A filename is required.")
        sections = extract_document(display_name, payload)
        chunks = [
            _Chunk(
                citation=f"{display_name}, {location}, chunk {number}",
                text=chunk,
                tokens=_tokens(chunk),
                filename=display_name,
                page=int(location[5:]) if location.startswith("page ") else None,
            )
            for location, text in sections
            for number, chunk in enumerate(_chunk_text(text), start=1)
        ]
        if not chunks:
            raise DocumentIngestionError("No readable text was found in the document.")
        document_id = str(uuid.uuid4())
        info = DocumentInfo(document_id, display_name, len(chunks))
        with SessionLocal() as db:
            db.add(
                StoredDocument(
                    id=document_id,
                    user_id=user_id,
                    filename=display_name,
                    chunk_count=len(chunks),
                )
            )
            db.flush()
            db.add_all(
                [
                    StoredChunk(
                        document_id=document_id,
                        citation=chunk.citation,
                        text=chunk.text,
                        tokens=chunk.tokens,
                        filename=chunk.filename,
                        page=chunk.page,
                    )
                    for chunk in chunks
                ]
            )
            db.commit()
        return info

    def list_documents(self, user_id: str) -> list[DocumentInfo]:
        with SessionLocal() as db:
            rows = db.scalars(
                select(StoredDocument)
                .where(StoredDocument.user_id == user_id)
                .order_by(StoredDocument.id)
            ).all()
            return [DocumentInfo(row.id, row.filename, row.chunk_count) for row in rows]

    def remove(self, user_id: str, document_id: str) -> bool:
        with SessionLocal() as db:
            row = db.scalar(
                select(StoredDocument).where(
                    StoredDocument.id == document_id,
                    StoredDocument.user_id == user_id,
                )
            )
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True

    def search(self, user_id: str, query: str, limit: int = 5) -> list[Evidence]:
        query_tokens = [token for token in _tokens(query) if token not in QUERY_STOPWORDS]
        query_terms = set(query_tokens)
        if not query_terms:
            return []
        with SessionLocal() as db:
            chunks = [
                _Chunk(
                    citation=row.citation,
                    text=row.text,
                    tokens=row.tokens,
                    filename=row.filename,
                    page=row.page,
                )
                for row in db.scalars(
                    select(StoredChunk)
                    .join(StoredDocument, StoredChunk.document_id == StoredDocument.id)
                    .where(StoredDocument.user_id == user_id)
                ).all()
            ]
        if not chunks:
            return []
        document_frequency = Counter(
            term for term in query_terms for chunk in chunks if term in set(chunk.tokens)
        )
        total_chunks = len(chunks)
        scored: list[Evidence] = []
        for chunk in chunks:
            term_counts = Counter(chunk.tokens)
            matched = query_terms.intersection(term_counts)
            coverage = len(matched) / len(query_terms)
            if not matched or coverage < 0.2:
                continue
            score = sum(
                math.log(
                    1
                    + (total_chunks - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                * (term_counts[term] * 2.2)
                / (term_counts[term] + 1.2)
                for term in matched
            )
            scored.append(
                Evidence(
                    citation=chunk.citation,
                    text=chunk.text,
                    score=score * coverage,
                    filename=chunk.filename,
                    page=chunk.page,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]


persistent_document_store = PersistentDocumentStore()
