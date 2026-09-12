from __future__ import annotations

from typing import Any, Dict


def enrich_metadata(document: Dict[str, Any], text: str) -> Dict[str, Any]:
    metadata = dict(document.get("metadata", {}))
    metadata.setdefault("title", document.get("title", "unknown"))
    metadata.setdefault("source", document.get("source", "unknown"))
    metadata.setdefault("section", document.get("section", "general"))
    metadata.setdefault("version", document.get("version", "v1"))

    for key in ["error_code", "product", "application", "incident_id"]:
        if key in metadata:
            metadata[key] = metadata[key]

    metadata["text_length"] = len(text)
    return metadata
