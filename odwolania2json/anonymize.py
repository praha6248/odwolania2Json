"""Redaction of personal data in PDFs: names of people, PESEL numbers, e-mail addresses and phone numbers.

Names come from the extracted fields (any key with imie_nazwisko, pesel or mail), other data from patterns in the
text. Every occurrence is found in the pdfium text layer, including inflected forms of names (the word is matched
from its start and the box extends to the end of the word). Pages are rendered as images with black boxes and saved
as a new PDF, so the redacted text is gone and cannot be copied out.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

PERSONAL_KEYS = ("imie_nazwisko", "pesel", "mail")
PATTERNS = {
    "pesel": r"(?<!\d)\d{11}(?!\d)",
    "email": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "telefon": r"(?<!\d)(?:\+48[ -]?)?\d{3}[ -]\d{3}[ -]\d{3}(?!\d)",
}


def valid_pesel(number: str) -> bool:
    """Check the PESEL control digit."""
    weights = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]
    return len(number) == 11 and number.isdigit() and (10 - sum(int(d) * w for d, w in zip(number, weights)) % 10) % 10 == int(number[-1])


def personal_values(node: Any, key: str = "") -> list[str]:
    """Personal values in extracted data: leaves under keys naming a person, a PESEL or an e-mail."""
    if isinstance(node, dict):
        return [v for k, item in node.items() for v in personal_values(item, k)]
    if isinstance(node, list):
        return [v for item in node for v in personal_values(item, key)]
    if node and isinstance(node, str) and any(p in key for p in PERSONAL_KEYS):
        return [node]
    return []


def terms(fields: list[dict[str, Any]], text: str, related: list[dict[str, Any]] | None = None) -> list[tuple[str, str]]:
    """Search terms (kind, text): person name parts from the fields (also of related documents of the case) and pattern matches from the text."""
    out: list[tuple[str, str]] = []
    for field in [*fields, *(related or [])]:
        for value in personal_values({field["field"]: field["value"]}):
            if "@" in value or value.isdigit():
                out.append(("dane", value))
                continue
            for part in re.findall(r"[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:-[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?", value):
                out.append(("osoba", part[:-1] if len(part) >= 5 else part))
    for kind, pattern in PATTERNS.items():
        for match in re.finditer(pattern, text):
            value = match.group(0)
            if kind != "pesel" or valid_pesel(value):
                out.append((kind, value))
    return list(dict.fromkeys(out))


def find_boxes(textpage: Any, term: str, whole_start: bool) -> list[tuple[float, float, float, float]]:
    """Boxes of every occurrence of a term; for names the match must start a word and extends to the word end."""
    text = textpage.get_text_range()
    boxes = []
    searcher = textpage.search(term, match_case=not whole_start)
    while (match := searcher.get_next()) is not None:
        index, length = match
        if whole_start:
            if index > 0 and text[index - 1:index].isalpha():
                continue
            limit = len(term) + (3 if len(term) < 5 else 40)
            while index + length < len(text) and length < limit and (text[index + length].isalpha() or text[index + length] == "-"):
                length += 1
            if index + length < len(text) and text[index + length].isalpha():
                continue
        for k in range(textpage.count_rects(index, length)):
            boxes.append(textpage.get_rect(k))
    return boxes


def redact(path: Path, fields: list[dict[str, Any]], text: str, related: list[dict[str, Any]] | None = None, scale: float = 2.0) -> tuple[bytes, dict[str, int]]:
    """Return the redacted PDF and the number of covered fragments per kind of data."""
    import pypdfium2 as pdfium
    from PIL import ImageDraw

    from .ocr import PDFIUM_LOCK

    wanted = terms(fields, text, related)
    counts: dict[str, int] = {}
    images = []
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            for page in pdf:
                textpage = page.get_textpage()
                height = page.get_size()[1]
                image = page.render(scale=scale).to_pil().convert("RGB")
                draw = ImageDraw.Draw(image)
                for kind, term in wanted:
                    boxes = find_boxes(textpage, term, kind == "osoba")
                    counts[kind] = counts.get(kind, 0) + len(boxes)
                    for left, bottom, right, top in boxes:
                        draw.rectangle([left * scale - 2, (height - top) * scale - 2, right * scale + 2, (height - bottom) * scale + 2], fill="black")
                images.append(image)
        finally:
            pdf.close()
    buffer = io.BytesIO()
    images[0].save(buffer, format="PDF", save_all=True, append_images=images[1:], resolution=72 * scale)
    return buffer.getvalue(), {k: v for k, v in counts.items() if v}
