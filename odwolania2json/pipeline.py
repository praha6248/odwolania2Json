"""End-to-end processing: PDF -> text -> class -> fields -> JSON files."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import extractors
from .classifier import Classification, classify
from .config import Settings, load_settings
from .engine import extract
from .llm import LLMClient
from .pdftext import extract_text

log = logging.getLogger("odwolania2json")


@dataclass
class DocumentResult:
    """Everything known about one processed PDF."""

    path: Path
    doc_type: str | None
    classification: Classification
    data: dict[str, Any] | None
    fields: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    seconds: float = 0.0
    error: str | None = None

    def trace(self) -> dict[str, Any]:
        """Return a transparent, serializable account of how the output was produced."""
        return {
            "file": self.path.name,
            "doc_type": self.doc_type,
            "classification": {
                "score": self.classification.score,
                "scores": self.classification.scores,
                "matched": self.classification.matched,
            },
            "fields": self.fields,
            "seconds": round(self.seconds, 3),
            "error": self.error,
        }


class Processor:
    """Processes PDFs according to the loaded configuration."""

    def __init__(self, settings: Settings | None = None, use_llm: bool | None = None) -> None:
        """Create a processor with given (or default) settings and optional LLM support."""
        self.settings = settings or load_settings()
        enabled = self.settings.llm.get("enabled", False) if use_llm is None else use_llm
        self.llm = LLMClient(self.settings.llm) if enabled else None

    def process_text(self, text: str, path: Path, forced_type: str | None = None) -> DocumentResult:
        """Classify and extract structured data from already extracted text."""
        started = time.perf_counter()
        cls = classify(self.settings, text, path.name)
        if forced_type:
            cls = Classification(forced_type, cls.scores.get(forced_type, 0.0), cls.scores, cls.matched)
        doc_type = self.settings.get_type(cls.doc_type) if cls.doc_type else None
        if doc_type is None:
            return DocumentResult(path, None, cls, None, text=text, seconds=time.perf_counter() - started)
        data, ctx = extract(text, doc_type)
        if self.llm is not None:
            data = self.llm.refine(doc_type, text, data, ctx)
        fields = [r.to_dict() for r in ctx.results.values()]
        return DocumentResult(path, doc_type.name, cls, data, fields, text, time.perf_counter() - started)

    def process_pdf(self, path: str | Path, forced_type: str | None = None) -> DocumentResult:
        """Process a single PDF file, never raising on malformed input."""
        path = Path(path)
        try:
            text = extract_text(path).text
        except Exception as exc:
            log.exception("Cannot read %s", path)
            return DocumentResult(path, None, Classification(None, 0.0), None, error=str(exc))
        return self.process_text(text, path, forced_type)

    def process_tree(self, input_dir: str | Path, output_dir: str | Path, trace_dir: str | Path | None = None) -> list[DocumentResult]:
        """Process every PDF under input_dir, mirroring the folder tree into output_dir."""
        input_dir, output_dir = Path(input_dir), Path(output_dir)
        results = []
        for pdf in sorted(p for p in input_dir.rglob("*") if p.suffix.lower() == ".pdf"):
            result = self.process_pdf(pdf)
            results.append(result)
            relative = pdf.relative_to(input_dir).with_suffix(".json")
            if result.data is not None:
                write_json(output_dir / relative, result.data)
            if trace_dir is not None:
                write_json(Path(trace_dir) / relative.with_suffix(".trace.json"), result.trace())
            log.info("%s -> %s", pdf.relative_to(input_dir), result.doc_type or "skipped")
        return results


def write_json(path: Path, data: Any) -> None:
    """Write data as pretty UTF-8 JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
