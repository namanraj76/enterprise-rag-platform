from __future__ import annotations

from pathlib import Path
from typing import List

from app.core.models import SourceDocument


class DocumentLoader:
    """Loads documents from a local directory and converts them into SourceDocument objects."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def load(self) -> List[SourceDocument]:
        documents: List[SourceDocument] = []
        if not self.directory.exists():
            return documents

        for file_path in sorted(self.directory.glob("*.txt")):
            content = file_path.read_text(encoding="utf-8")
            doc_id = file_path.stem
            documents.append(
                SourceDocument(
                    doc_id=doc_id,
                    title=file_path.stem.replace("_", " ").title(),
                    content=content,
                    source=str(file_path.name),
                    section="general",
                    version="v1",
                    metadata={"file_name": file_path.name},
                )
            )
        return documents
