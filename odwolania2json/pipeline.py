"""End-to-end processing: PDF -> text -> class -> fields -> JSON files."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    ocr: dict[str, Any] | None = None

    @property
    def message(self) -> str | None:
        """Human readable reason why no JSON was produced, or None when extraction succeeded."""
        if self.error:
            return f"Nie udało się odczytać pliku: {self.error}"
        if self.doc_type is None:
            scores = self.classification.scores
            best = max(scores, key=lambda k: scores[k]) if scores else None
            detail = f" (najbliższy: {best}, {scores[best]:g} pkt)" if best else ""
            return f"Nie udało się dopasować typu dokumentu{detail}."
        return None

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
            "message": self.message,
            "ocr": self.ocr,
            "error": self.error,
        }


class Processor:
    """Processes PDFs according to the loaded configuration."""

    def __init__(self, settings: Settings | None = None, use_llm: bool | None = None) -> None:
        """Create a processor with given (or default) settings and optional LLM support."""
        self.settings = settings or load_settings()
        enabled = self.settings.llm.get("enabled", False) if use_llm is None else use_llm
        self.llm = LLMClient(self.settings.llm) if enabled else None

    def llm_for(self, use_llm: bool | None) -> LLMClient | None:
        """Return the LLM client to use: the configured one, or one forced on/off for a single call."""
        if use_llm is None:
            return self.llm
        return (self.llm or LLMClient(self.settings.llm)) if use_llm else None

    def process_text(self, text: str, path: Path, forced_type: str | None = None, use_llm: bool | None = None) -> DocumentResult:
        """Classify and extract structured data from already extracted text."""
        started = time.perf_counter()
        cls = classify(self.settings, text, path.name)
        if forced_type:
            cls = Classification(forced_type, cls.scores.get(forced_type, 0.0), cls.scores, cls.matched)
        doc_type = self.settings.get_type(cls.doc_type) if cls.doc_type else None
        if doc_type is None:
            return DocumentResult(path, None, cls, None, text=text, seconds=time.perf_counter() - started)
        data, ctx = extract(text, doc_type)
        llm = self.llm_for(use_llm)
        if llm is not None:
            accurate = self.settings.llm.get("mode", "fast") == "accurate"
            data = (llm.verify if accurate else llm.refine)(doc_type, text, data, ctx)
        self.last_context = ctx
        fields = [r.to_dict() for r in ctx.results.values()]
        return DocumentResult(path, doc_type.name, cls, data, fields, text, time.perf_counter() - started)

    def process_pdf(self, path: str | Path, forced_type: str | None = None, use_llm: bool | None = None) -> DocumentResult:
        """Process a single PDF file, never raising on malformed input."""
        path = Path(path)
        started = time.perf_counter()
        try:
            doc = extract_text(path, self.settings.ocr)
        except Exception as exc:
            log.exception("Cannot read %s", path)
            return DocumentResult(path, None, Classification(None, 0.0), None, error=str(exc))
        result = self.process_text(doc.text, path, forced_type, use_llm)
        result.seconds = time.perf_counter() - started
        if doc.ocr_pages:
            result.ocr = {"engine": doc.ocr_engine, "pages": [i + 1 for i in doc.ocr_pages]}
        return result

    def safe_process(self, pdf: Path) -> DocumentResult:
        """Process one PDF, turning any unexpected exception into an error result."""
        try:
            return self.process_pdf(pdf)
        except Exception as exc:
            log.exception("%s: processing failed", pdf)
            return DocumentResult(path=pdf, doc_type=None, classification=Classification(None, 0.0), data=None, error=str(exc))

    def process_tree(self, input_dir: str | Path, output_dir: str | Path, trace_dir: str | Path | None = None, workers: int = 1) -> list[DocumentResult]:
        """Process every PDF under input_dir, mirroring the folder tree into output_dir, optionally in parallel processes."""
        input_dir, output_dir = Path(input_dir), Path(output_dir)
        pdfs = sorted(p for p in input_dir.rglob("*") if p.suffix.lower() == ".pdf" and p.is_file())
        if workers > 1 and len(pdfs) > 1:
            from concurrent.futures import ProcessPoolExecutor

            with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(self.settings, self.llm is not None, workers)) as pool:
                processed = list(pool.map(_process_in_worker, pdfs, chunksize=1))
        else:
            processed = [self.safe_process(pdf) for pdf in pdfs]
        results = []
        for pdf, result in zip(pdfs, processed):
            relative = pdf.relative_to(input_dir).with_suffix(".json")
            results.append(result)
            if result.data is not None:
                write_json(output_dir / relative, result.data)
            elif self.settings.unmatched_output == "empty_json":
                write_json(output_dir / relative, {})
            if trace_dir is not None:
                write_json(Path(trace_dir) / relative.with_suffix(".trace.json"), result.trace())
            if result.data is None:
                log.warning("%s: %s", pdf.relative_to(input_dir), result.message)
            else:
                log.info("%s -> %s", pdf.relative_to(input_dir), result.doc_type)
        return results


_WORKER: Processor | None = None


def _init_worker(settings: Settings, use_llm: bool, workers: int) -> None:
    """Create the processor of a worker process and share the CPU cores between the workers' OCR."""
    global _WORKER
    from . import ocr

    ocr.THREADS = max(1, (os.cpu_count() or workers) // workers)
    _WORKER = Processor(settings, use_llm=use_llm)


def _process_in_worker(pdf: Path) -> DocumentResult:
    """Process one PDF in a worker process."""
    assert _WORKER is not None
    return _WORKER.safe_process(pdf)


def write_json(path: Path, data: Any) -> None:
    """Write data as pretty UTF-8 JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
