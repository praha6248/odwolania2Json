"""OCR fallback for scanned PDFs using CPU-only open-source engines (Tesseract or RapidOCR)."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger("odwolania2json.ocr")

OCR_FIXES = [
    ("ž", "ż"),
    ("Ž", "Ż"),
    (r"\bz 0\.o\.", "z o.o."),
    (r"\b0\.o\.", "o.o."),
    (r"\bo\.0\.", "o.o."),
    (r"\bo\.0\b", "o.o"),
    (r"\bS\.A,", "S.A.,"),
    (r"(?<=\d)O(?=\d)", "0"),
    (r"(?<=\d)[lI](?=\d)", "1"),
    (r"\bKRS[:.]?\s*(?=\d)", "KRS "),
    (r"\bNlP\b|\bNIp\b", "NIP"),
]


def fix_ocr_text(text: str) -> str:
    """Repair frequent OCR confusions in identifiers and legal forms."""
    for pattern, replacement in OCR_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


def render_pages(path: Path, scale: float, pages: list[int] | None = None) -> list[Any]:
    """Render PDF pages to RGB numpy arrays."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    indices = pages if pages is not None else list(range(len(pdf)))
    return [pdf[i].render(scale=scale).to_numpy() for i in indices]


def boxes_to_text(boxes: list[Any], texts: list[str]) -> str:
    """Rebuild reading order by grouping OCR boxes into lines by vertical position."""
    items = []
    for box, text in zip(boxes, texts):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((min(ys), max(ys), min(xs), text))
    items.sort(key=lambda i: (i[0], i[2]))
    lines: list[list[tuple[float, float, float, str]]] = []
    for item in items:
        if lines:
            last = lines[-1]
            top = min(i[0] for i in last)
            bottom = max(i[1] for i in last)
            height = bottom - top
            if item[0] < top + height * 0.5:
                last.append(item)
                continue
        lines.append([item])
    return "\n".join(" ".join(i[3] for i in sorted(line, key=lambda i: i[2])) for line in lines)


@lru_cache(maxsize=1)
def _rapidocr_engine() -> Any:
    """Create (once) a RapidOCR engine with the Latin recognition model covering Polish diacritics."""
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    return RapidOCR(
        params={
            "Global.log_level": "warning",
            "Rec.lang_type": LangRec.LATIN,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
        }
    )


def rapidocr_page(image: Any) -> str:
    """OCR a page image with RapidOCR."""
    result = _rapidocr_engine()(image)
    if result.boxes is None:
        return ""
    return boxes_to_text(list(result.boxes), list(result.txts))


def tesseract_available() -> bool:
    """Tell whether the tesseract binary with Polish data is installed."""
    exe = shutil.which("tesseract")
    if not exe:
        return False
    try:
        langs = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "pol" in langs.split()


def tesseract_page(image: Any) -> str:
    """OCR a page image with Tesseract (Polish model)."""
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / "page.png"
        Image.fromarray(image).save(file)
        out = subprocess.run(
            ["tesseract", str(file), "-", "-l", "pol", "--psm", "4"], capture_output=True, text=True, timeout=300
        )
    return out.stdout


ENGINES = {"tesseract": (tesseract_available, tesseract_page), "rapidocr": (lambda: _importable("rapidocr"), rapidocr_page)}


def _importable(module: str) -> bool:
    """Check whether a Python module can be imported."""
    try:
        __import__(module)
        return True
    except Exception:
        return False


def pick_engine(order: list[str]) -> str | None:
    """Return the first available OCR engine from the preferred order."""
    for name in order:
        check = ENGINES.get(name)
        if check and check[0]():
            return name
    return None


def cache_dir(cfg: dict[str, Any]) -> Path | None:
    """Return the OCR cache directory, or None when caching is disabled."""
    if cfg.get("cache", True) is False:
        return None
    base = os.environ.get("O2J_CACHE_DIR") or cfg.get("cache_dir") or Path.home() / ".cache" / "odwolania2json"
    return Path(base) / "ocr"


def ocr_pages(path: Path, pages: list[int], cfg: dict[str, Any]) -> tuple[dict[int, str], str | None]:
    """OCR the given page indices of a PDF (with an on-disk cache), returning texts per page and the engine used."""
    engine = pick_engine(cfg.get("engines", ["tesseract", "rapidocr"]))
    if engine is None:
        log.warning("No OCR engine available for %s", path)
        return {}, None
    scale = float(cfg.get("scale", 2.0))
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    folder = cache_dir(cfg)
    texts: dict[int, str] = {}
    todo = []
    for index in pages:
        cached = folder / f"{digest}-{index}-{engine}-{scale}.txt" if folder else None
        if cached and cached.exists():
            texts[index] = cached.read_text(encoding="utf-8")
        else:
            todo.append(index)
    if todo:
        run = ENGINES[engine][1]
        for index, image in zip(todo, render_pages(path, scale, todo)):
            texts[index] = run(image)
            if folder:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{digest}-{index}-{engine}-{scale}.txt").write_text(texts[index], encoding="utf-8")
    return {index: fix_ocr_text(texts[index]) for index in pages}, engine
