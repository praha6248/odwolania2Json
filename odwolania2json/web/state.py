"""Shared state of the web application: the document store, current settings and the processor."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .. import __version__
from ..cases import case_values
from ..config import load_settings
from ..pipeline import DocumentResult, Processor


class Store:
    """In-memory registry of uploaded documents backed by a temporary directory."""

    def __init__(self) -> None:
        """Create an empty store with its own scratch directory."""
        self.root = Path(tempfile.mkdtemp(prefix="o2j-"))
        self.items: dict[str, dict[str, Any]] = {}

    def add(self, filename: str, content: bytes) -> tuple[str, Path]:
        """Persist an uploaded file and return its id and path."""
        doc_id = uuid.uuid4().hex[:12]
        folder = self.root / doc_id
        folder.mkdir(parents=True)
        path = folder / Path(filename).name
        path.write_bytes(content)
        self.items[doc_id] = {"id": doc_id, "filename": path.name, "path": path}
        return doc_id, path

    def get(self, doc_id: str) -> dict[str, Any]:
        """Return a stored item or raise 404."""
        if doc_id not in self.items:
            raise HTTPException(status_code=404, detail="Unknown document")
        return self.items[doc_id]

    def remove(self, doc_id: str) -> None:
        """Delete a stored item and its files."""
        item = self.items.pop(doc_id, None)
        if item:
            shutil.rmtree(item["path"].parent, ignore_errors=True)

    def processed(self) -> list[dict[str, Any]]:
        """Results of processed documents in upload order."""
        return [i["result"] for i in self.items.values() if "result" in i]


def serialize(doc_id: str, result: DocumentResult, settings_labels: dict[str, str], case_spec: dict[str, str] | None = None) -> dict[str, Any]:
    """Build the API representation of a processed document."""
    values = {f["field"]: f["value"] for f in result.fields}
    return {
        "id": doc_id,
        "filename": result.path.name,
        "doc_type": result.doc_type,
        "doc_label": settings_labels.get(result.doc_type or "", "Spoza puli"),
        "data": result.data,
        "fields": result.fields,
        "case_values": case_values(case_spec or {}, values),
        "classification": result.trace()["classification"],
        "seconds": round(result.seconds, 3),
        "error": result.error,
        "message": result.message,
        "text": result.text,
        "ocr": result.ocr,
    }


class AppState:
    """Settings, processor and uploaded documents shared by all routes."""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        """Load the configuration and create an empty document store."""
        self.config_dir = config_dir
        self.settings = load_settings(config_dir)
        self.processor = Processor(self.settings)
        self.store = Store()

    def labels(self) -> dict[str, str]:
        """Map document type names to human readable labels."""
        return {t.name: t.label for t in self.settings.document_types}

    def remember(self, doc_id: str, result: DocumentResult) -> None:
        """Store the serialized result and the extraction context needed for manual corrections."""
        doc_type = self.settings.get_type(result.doc_type) if result.doc_type else None
        self.store.items[doc_id]["result"] = serialize(doc_id, result, self.labels(), doc_type.case if doc_type else None)
        self.store.items[doc_id]["context"] = getattr(self.processor, "last_context", None) if doc_type else None

    def llm_client(self) -> Any:
        """Return an LLM client for the current settings or fail with a clear message."""
        from ..llm import LLMClient

        if not self.settings.llm.get("base_url"):
            raise HTTPException(status_code=400, detail="Skonfiguruj model językowy w Ustawieniach.")
        return LLMClient(self.settings.llm)

    def rebuild_processor(self) -> None:
        """Create a new processor after the settings changed."""
        self.processor = Processor(self.settings)

    def reload(self) -> None:
        """Reload the YAML configuration from disk."""
        self.settings = load_settings(self.config_dir)
        self.rebuild_processor()

    def info(self) -> dict[str, Any]:
        """Version, configured document types and LLM status."""
        return {
            "version": __version__,
            "llm": bool(self.processor.llm),
            "llm_model": self.settings.llm.get("model") if self.processor.llm else None,
            "types": [
                {"name": t.name, "label": t.label, "fields": list(t.fields), "optional": [n for n, spec in t.fields.items() if (spec or {}).get("optional")], "source": t.source.name if t.source else None}
                for t in self.settings.document_types
            ],
        }
