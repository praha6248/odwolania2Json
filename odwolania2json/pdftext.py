"""Text extraction from PDF files."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader


@dataclass
class DocumentText:
    """Plain text of a PDF document together with per-page content and OCR information."""

    path: Path
    pages: list[str] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    ocr_engine: str | None = None

    @property
    def text(self) -> str:
        """Return the full document text with pages joined by newlines."""
        return "\n".join(self.pages)


SPACING_ACCENTS = {
    "´": "\u0301",
    "˙": "\u0307",
    "˛": "\u0328",
    "¸": "\u0327",
    "ˇ": "\u030c",
}


def join_spacing_accents(text: str) -> str:
    """Merge spacing accents emitted by some PDF generators (e.g. LaTeX: '´s', '˙z', '˛a') with their letters."""
    for accent, combining in SPACING_ACCENTS.items():
        text = re.sub(rf"{accent}\s?([A-Za-z])", lambda m: m.group(1) + combining, text)
    return text


def clean_text(text: str) -> str:
    """Normalize unicode, whitespace and typographic artefacts in extracted text."""
    text = join_spacing_accents(text)
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00ad", "").replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"(?im)^\s*Strona\s+\d+\s+z\s+\d+\s*$\n?", "", text)
    text = re.sub(r"(?i)\s*Strona\s+\d+\s+z\s+\d+\s*(?=\n)", "", text)
    return text.strip()


def extract_text(path: str | Path, ocr: dict[str, Any] | None = None) -> DocumentText:
    """Read a PDF and return cleaned text per page, running OCR on pages without a usable text layer."""
    path = Path(path)
    reader = PdfReader(str(path))
    pages = [clean_text(page.extract_text() or "") for page in reader.pages]
    doc = DocumentText(path=path, pages=pages)
    ocr = ocr or {}
    if not ocr.get("enabled", True):
        return doc
    min_chars = int(ocr.get("min_chars_per_page", 40))
    max_pages = int(ocr.get("max_pages", 4))
    missing = [i for i, text in enumerate(pages) if len(re.sub(r"\s", "", text)) < min_chars][:max_pages]
    if not missing:
        return doc
    from .ocr import ocr_pages

    texts, engine = ocr_pages(path, missing, ocr)
    for index, text in texts.items():
        doc.pages[index] = clean_text(text)
    doc.ocr_pages = sorted(texts)
    doc.ocr_engine = engine
    return doc


def fold(text: str) -> str:
    """Strip Polish diacritics so that OCR output without accents still matches keywords."""
    text = text.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def compact(text: str) -> str:
    """Return a lowercase, accent-free copy of text without whitespace for robust keyword matching."""
    return fold(re.sub(r"\s+", "", text)).lower()
