"""Find where an extracted value sits on the PDF pages, for highlighting it in the preview.

The evidence span of a field points into the cleaned document text, not into the PDF, so the matched text (line by
line) and the value itself are searched in the PDF text layer with pdfium. When a term occurs several times, the
occurrence closest to the relative position of the evidence span is chosen. On scanned pages without a text layer
the terms are matched in the OCR text lines and their boxes (see ocr.ocr_lines).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

MIN_TERM = 3


def terms(field: dict[str, Any], text: str) -> tuple[list[str], list[str]]:
    """Search terms for a field: the lines of its evidence span, and its scalar values as a fallback."""
    span: list[str] = []
    start, end = field.get("start"), field.get("end")
    if start is not None and end is not None and text:
        span = [line for line in (re.sub(r"\s+", " ", part).strip() for part in text[start:end].splitlines()) if len(line) >= MIN_TERM]
    values = [str(v) for v in _leaves(field.get("value")) if v is not None and not isinstance(v, bool) and len(str(v)) >= MIN_TERM]
    return list(dict.fromkeys(span)), list(dict.fromkeys(values))


def _leaves(node: Any) -> list[Any]:
    """Scalar leaves of nested lists and dicts."""
    if isinstance(node, dict):
        return [leaf for v in node.values() for leaf in _leaves(v)]
    if isinstance(node, list):
        return [leaf for v in node for leaf in _leaves(v)]
    return [node]


SCANNED_CHARS = 20  # a page with fewer text-layer characters is treated as a scan


def locate(path: Path, field: dict[str, Any], text: str, ocr: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return highlight boxes [{page, rects: [[x0, y0, x1, y1], ...]}] with coordinates as fractions of the page size."""
    import pypdfium2 as pdfium

    from .ocr import PDFIUM_LOCK

    groups = terms(field, text)
    if not any(groups):
        return []
    anchor = (field.get("start") or 0) / max(1, len(text))
    hits: dict[int, list[list[float]]] = {}
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            pages = [(pdf[i], pdf[i].get_textpage()) for i in range(len(pdf))]
            counts = [tp.count_chars() for _, tp in pages]
            total = max(1, sum(counts))
            for group in groups:
                for term in group:
                    best = _closest(pages, counts, total, term, anchor)
                    if best is None:
                        continue
                    number, index, length = best
                    page, tp = pages[number]
                    width, height = page.get_size()
                    for k in range(tp.count_rects(index, length)):
                        left, bottom, right, top = tp.get_rect(k)
                        hits.setdefault(number, []).append([left / width, 1 - top / height, right / width, 1 - bottom / height])
                if hits:
                    break
            scanned = [i for i, count in enumerate(counts) if count < SCANNED_CHARS]
        finally:
            pdf.close()
    if not hits and scanned and ocr is not None:
        hits = _locate_scanned(path, scanned[: int(ocr.get("max_pages", 4))], groups, anchor, ocr)
    return [{"page": number + 1, "rects": rects} for number, rects in sorted(hits.items())]


def _locate_scanned(path: Path, pages: list[int], groups: tuple[list[str], list[str]], anchor: float, ocr: dict[str, Any]) -> dict[int, list[list[float]]]:
    """Boxes of the evidence lines (or values) in the OCR lines of scanned pages, one best match per term."""
    from .ocr import find_in_lines, ocr_lines

    lines = {number: ocr_lines(path, number, ocr) for number in pages}
    hits: dict[int, list[list[float]]] = {}
    for group in groups:
        for term in group:
            candidates = [
                (score, -abs((number + (box[1] + box[3]) / 2) / len(pages) - anchor), number, box)
                for number, page_lines in lines.items()
                for score, box in find_in_lines(page_lines, term)
            ]
            if candidates:
                _, _, number, box = max(candidates)
                hits.setdefault(number, []).append(list(box))
        if hits:
            break
    return hits


def _closest(pages: list[Any], counts: list[int], total: int, term: str, anchor: float) -> tuple[int, int, int] | None:
    """Occurrence of a term (page, char index, length) closest to the relative anchor position."""
    best = None
    offset = 0
    for number, ((_, tp), count) in enumerate(zip(pages, counts)):
        searcher = tp.search(term, match_case=False)
        for _ in range(50):
            match = searcher.get_next()
            if match is None:
                break
            distance = abs((offset + match[0]) / total - anchor)
            if best is None or distance < best[0]:
                best = (distance, number, match[0], match[1])
        offset += count
    return best[1:] if best else None
