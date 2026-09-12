from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SourceDocument:
    doc_id: str
    title: str
    content: str
    source: str = "unknown"
    section: str = "general"
    version: str = "v1"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    source: str
    section: str
    version: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    chunk_id: str
    doc_id: str
    text: str
    source: str
    section: str
    version: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Answer:
    answer: str
    citations: List[str]
    evidence: List[RetrievalResult]
    validation: Optional[Dict[str, Any]] = None
