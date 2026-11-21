"""Text extraction from PDF files."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader


@dataclass
class DocumentText:
    """Plain text of a PDF document together with per-page content."""

    path: Path
    pages: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Return the full document text with pages joined by newlines."""
        return "\n".join(self.pages)


def clean_text(text: str) -> str:
    """Normalize unicode, whitespace and typographic artefacts in extracted text."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def extract_text(path: str | Path) -> DocumentText:
    """Read a PDF file and return its cleaned text split into pages."""
    path = Path(path)
    reader = PdfReader(str(path))
    pages = [clean_text(page.extract_text() or "") for page in reader.pages]
    return DocumentText(path=path, pages=pages)


def compact(text: str) -> str:
    """Return a lowercase copy of text without whitespace, used for robust keyword matching."""
    return re.sub(r"\s+", "", text).lower()
