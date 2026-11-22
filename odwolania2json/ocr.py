"""OCR fallback for scanned PDFs using CPU-only open-source engines (Tesseract or RapidOCR)."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger("odwolania2json.ocr")
PDFIUM_LOCK = threading.Lock()

OCR_FIXES = [
    (r"\bSp[óo][fłlt1]k(?=[aęiąo])", "Spółk"),
    (r"\bsp[óo][fłlt1]k(?=[aęiąo])", "spółk"),
    (r"\bograniczon[ao]\s+odpowiedzialno[sś]ci[ąa]\b", "ograniczoną odpowiedzialnością"),
    (r"\bOdwo[lł]uj[aą]c(?=[yeag])", "Odwołując"),
    (r"\bZamawiaj[aą]c(?=[yeag])", "Zamawiając"),
    (r"\bPe[lłi]nomocni", "Pełnomocni"),
    (r"\bpe[lłi]nomocni", "pełnomocni"),
    (r"(?<=[a-ząćęłńóśźż]{3})q\b", "ą"),
    (r"(?<=\w)@\.(?=\w)", "@"),
    (r"(\bpn\.\s*)(?=[A-ZĄĆĘŁŃÓŚŹŻ][^„“\"”\n]{0,160}(?:\n[^„“\"”\n]{0,160}){0,3}[\"”])", r"\1„"),
    (r"(\(dalej(?:\s+łącznie)?\s*:\s*)(?=[A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźż]*[\"”])", r"\1„"),
    (r"\b(przez|Przez)\.\s*(?=[A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ])", r"\1 "),
    (r"\bODWO[LŁ]ANIE\b", "ODWOŁANIE"),
    (r"\bP[EĘ][LŁ]NOMOCNICTWO\b", "PEŁNOMOCNICTWO"),
    (r"\bTytu[fłlt]\b", "Tytuł"),
    (r"\bop[fłlt]ata\b", "opłata"),
    (r"\bOp[fłlt]ata\b", "Opłata"),
    ("ž", "ż"),
    ("Ž", "Ż"),
    (r"\bz [0oO]\.[0oO]\.", "z o.o."),
    (r"\buf\.(?=\s)", "ul."),
    (r"\b0\.o\.", "o.o."),
    (r"\bo\.0\.", "o.o."),
    (r"\bo\.0\b", "o.o"),
    (r"\bS\.A,", "S.A.,"),
    (r"(?<=\d)[oO](?=[\d./-])", "0"),
    (r"(?<![\w])[oO](?=\d[./-][\doO]\d)", "0"),
    (r"(?<=\d[./-])[oO](?=\d)", "0"),
    (r"(?<=[\d/\s])[oO](?=\d{2})", "0"),
    (r"(?<=PL)[oO](?=\d)", "0"),
    (r"(?<=PL\d)[oO]", "0"),
    (r"(?<=\d)[lI](?=\d)", "1"),
    (r"\bKRS[:.]?\s*(?=\d)", "KRS "),
    (r"\bNlP\b|\bNIp\b", "NIP"),
    (r"(?<=Zespół\s)Szkot\b", "Szkół"),
    (r"\bSzkot(?=\s+(?:Technicznych|Ogólnokształcących|Zawodowych|nr\b|im\.|w\b))", "Szkół"),
    (r"\bJodtowsk", "Jodłowsk"),
    (r"(?<=[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż])·(?=[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż])", " "),
]


def fix_ocr_text(text: str) -> str:
    """Repair frequent OCR confusions in identifiers and legal forms."""
    for pattern, replacement in OCR_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


def skew_angle(image: Any, limit: float = 3.0, step: float = 0.2) -> float:
    """Estimate page skew in degrees by maximizing the variance of the horizontal projection profile."""
    import numpy as np
    from PIL import Image

    gray = Image.fromarray(image).convert("L")
    gray.thumbnail((1000, 1000))
    ink = Image.fromarray((np.asarray(gray) < 160).astype(np.uint8) * 255)
    best, best_score = 0.0, -1.0
    for angle in np.arange(-limit, limit + step / 2, step):
        profile = np.asarray(ink.rotate(float(angle), resample=Image.NEAREST, fillcolor=0)).sum(axis=1, dtype=np.float64)
        score = float(np.var(np.diff(profile)))
        if score > best_score:
            best, best_score = float(angle), score
    return best


def deskew(image: Any) -> Any:
    """Rotate a page image so text lines are horizontal."""
    import numpy as np
    from PIL import Image

    angle = skew_angle(image)
    if abs(angle) < 0.1:
        return image
    return np.asarray(Image.fromarray(image).rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255)))


def render_pages(path: Path, scale: float, pages: list[int] | None = None) -> list[Any]:
    """Render PDF pages to RGB numpy arrays and straighten them."""
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        indices = pages if pages is not None else list(range(len(pdf)))
        images = [pdf[i].render(scale=scale).to_numpy()[..., :3].copy() for i in indices]
        pdf.close()
    return [deskew(image) for image in images]


LAYOUT_VERSION = 6
LABEL = re.compile(r"^[A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ ]{2,30}:$")
FLOAT_STOP = re.compile(r"(?i)^(?:tel\b|e-?mail|ul\.|al\.|pl\.|os\.|\d{2}-\d{3}|KRS\b|NIP\b|REGON\b)")
PARTY_CAPTION = re.compile(r"(?i)^(?:odwo[lł]uj|zamawiaj|dotyczy|konsorcjum)")


def _group_lines(items: list[tuple[float, float, float, float, str]]) -> list[list[tuple[float, float, float, float, str]]]:
    """Group OCR boxes (top, bottom, left, right, text) into visual lines by vertical overlap."""
    lines: list[list[tuple[float, float, float, float, str]]] = []
    for item in sorted(items, key=lambda i: (i[0], i[2])):
        if lines:
            last = lines[-1]
            top = min(i[0] for i in last)
            bottom = max(i[1] for i in last)
            if item[0] < top + (bottom - top) * 0.5:
                last.append(item)
                continue
        lines.append([item])
    return [sorted(line, key=lambda i: i[2]) for line in lines]


def _float_labels(lines: list[list[tuple[float, float, float, float, str]]]) -> list[list[tuple[float, float, float, float, str]]]:
    """Move left-column labels ('Zamawiający:') above the right-column value block they are centred against."""
    out = [list(line) for line in lines]
    index = 0
    while index < len(out):
        line = out[index]
        head = line[0]
        if len(line) > 1 and LABEL.match(head[4].strip()):
            height = head[1] - head[0]
            column = line[1][2]
            start = index
            while start > 0:
                above = out[start - 1]
                below_top = min(i[0] for i in out[start])
                if FLOAT_STOP.match(" ".join(i[4] for i in above).strip()):
                    break
                if min(i[2] for i in above) <= head[3] or min(i[0] for i in above) < head[0] - 2.5 * height:
                    break
                if abs(min(i[2] for i in above) - column) > 2 * height:
                    break
                if below_top - max(i[1] for i in above) > 0.9 * height:
                    break
                start -= 1
            if start < index:
                out[index] = line[1:]
                out.insert(start, [head])
                index += 1
        index += 1
    return out


Line = list[tuple[float, float, float, float, str]]


def _height(line: Line) -> float:
    """Typical box height of a line."""
    return max(1.0, sorted(i[1] - i[0] for i in line)[len(line) // 2])


def _is_caption(text: str) -> bool:
    """Tell whether a box looks like a field caption (short, no digits)."""
    words = text.split()
    return 0 < len(words) <= 4 and not re.search(r"\d", text)


def _pair_label_rows(lines: list[Line]) -> list[Line]:
    """Turn a row of captions followed by an aligned row of values into caption-value lines."""
    out: list[Line] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        nxt = lines[index + 1] if index + 1 < len(lines) else None
        tolerance = 3 * _height(line)
        if (
            nxt is not None
            and len(line) >= 2
            and len(line) == len(nxt)
            and all(_is_caption(i[4]) for i in line)
            and not all(_is_caption(i[4]) for i in nxt)
            and all(abs(a[2] - b[2]) < tolerance for a, b in zip(line, nxt))
        ):
            out.extend([a, b] for a, b in zip(line, nxt))
            index += 2
            continue
        out.append(line)
        index += 1
    return out


def _split_colon_columns(lines: list[Line]) -> list[Line]:
    """Unfold side-by-side blocks headed by captions ending with ':' (e.g. two signature columns)."""
    out: list[Line] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if (
            len(line) >= 2
            and all(i[4].strip().endswith(":") and _is_caption(i[4]) for i in line)
            and not any(PARTY_CAPTION.match(i[4].strip()) for i in line)
        ):
            starts = [i[2] for i in line]
            height = _height(line)
            columns: list[list[Line]] = [[[item]] for item in line]
            bottom = max(i[1] for i in line)
            index += 1
            while index < len(lines):
                row = lines[index]
                if min(i[0] for i in row) - bottom > 2.5 * height:
                    break
                for item in row:
                    column = max((c for c, x in enumerate(starts) if item[2] >= x - height), default=0)
                    columns[column].append([item])
                bottom = max(i[1] for i in row)
                index += 1
            for column in columns:
                merged: list[Line] = []
                for piece in column:
                    if merged and abs(piece[0][0] - merged[-1][-1][0]) < 0.5 * height:
                        merged[-1].extend(piece)
                    else:
                        merged.append(piece)
                out.extend(merged)
            continue
        out.append(line)
        index += 1
    return out


def boxes_to_text(boxes: list[Any], texts: list[str]) -> str:
    """Rebuild reading order from OCR boxes: lines, caption rows, column blocks and floating labels."""
    items = []
    for box, text in zip(boxes, texts):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((min(ys), max(ys), min(xs), max(xs), text))
    lines = _float_labels(_split_colon_columns(_pair_label_rows(_group_lines(items))))
    return "\n".join(" ".join(i[4] for i in line) for line in lines if line)


THREADS = 0
AUTO_THRESHOLD = 0.8
AUTO_MARGIN = 0.05

RAPIDOCR_MODELS = {
    "auto": "PP-OCRv5 Latin first; a page whose text has under 80% known Polish words is read again with PP-OCRv6",
    "v6": "PP-OCRv6 small: multilingual detection and recognition with Polish, more robust on poor scans",
    "v5": "PP-OCRv5 mobile Latin recognition (the previous default)",
}


@lru_cache(maxsize=2)
def _rapidocr_engine(model: str = "v6") -> Any:
    """Create (once per model) a RapidOCR engine whose recognition covers Polish diacritics."""
    import onnxruntime
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    onnxruntime.set_default_logger_severity(3)  # hide hardware probing warnings (e.g. PCI bus ids on cloud VMs)
    params: dict[str, Any] = {"Global.log_level": "error", "Global.use_cls": False, "Det.thresh": 0.2, "Det.box_thresh": 0.3}
    if THREADS:
        params.update({"EngineConfig.onnxruntime.intra_op_num_threads": THREADS, "EngineConfig.onnxruntime.inter_op_num_threads": 1})
    if model == "v5":
        params.update({"Rec.lang_type": LangRec.LATIN, "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE})
    else:
        params.update({"Rec.lang_type": "pl", "Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType.SMALL})
    return RapidOCR(params=params)


def text_quality(text: str) -> float:
    """Share of words (3+ letters) found in the Polish lexicon; low values mean garbled OCR output."""
    from .spell import WORD, is_word

    words = WORD.findall(fix_ocr_text(text))
    return sum(is_word(w) for w in words) / len(words) if words else 0.0


def rapidocr_page(image: Any, model: str = "auto") -> str:
    """OCR a page image with RapidOCR; in auto mode a garbled page is read again with the PP-OCRv6 model."""
    if model == "auto":
        text = rapidocr_page(image, "v5")
        quality = text_quality(text)
        if quality < AUTO_THRESHOLD:
            retry = rapidocr_page(image, "v6")
            if text_quality(retry) > quality + AUTO_MARGIN:
                return retry
        return text
    result = _rapidocr_engine(model)(image)
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
    engine = pick_engine(cfg.get("engines", ["rapidocr", "tesseract"]))
    if engine is None:
        log.warning("No OCR engine available for %s", path)
        return {}, None
    scale = float(cfg.get("scale", 2.0))
    model = str(cfg.get("rapidocr_model", "auto")) if engine == "rapidocr" else ""
    variant = f"{engine}-{model}" if model and model != "v5" else engine
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    folder = cache_dir(cfg)
    texts: dict[int, str] = {}
    todo = []
    for index in pages:
        cached = folder / f"{digest}-{index}-{variant}-{scale}-v{LAYOUT_VERSION}.txt" if folder else None
        if cached and cached.exists():
            texts[index] = cached.read_text(encoding="utf-8")
        else:
            todo.append(index)
    if todo:
        run = (lambda image: rapidocr_page(image, model)) if engine == "rapidocr" else ENGINES[engine][1]
        for index, image in zip(todo, render_pages(path, scale, todo)):
            texts[index] = run(image)
            if folder:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{digest}-{index}-{variant}-{scale}-v{LAYOUT_VERSION}.txt").write_text(texts[index], encoding="utf-8")
    repaired = {index: fix_ocr_text(texts[index]) for index in pages}
    if cfg.get("spellcheck", True):
        from .spell import correct_text

        repaired = {index: correct_text(text, float(cfg.get("spellcheck_min_zipf", 2.0))) for index, text in repaired.items()}
    return repaired, engine


# --- Positions of text on scanned pages, for highlighting sources and redacting personal data -----------------------

Box = tuple[float, float, float, float]


def ocr_lines(path: Path, index: int, cfg: dict[str, Any]) -> list[tuple[Box, str]]:
    """Text lines of a scanned page with their boxes (x0, y0, x1, y1) as fractions of the page size, top-left origin.

    The page is rendered without straightening, so the boxes match the page as it is displayed. Results are cached
    on disk next to the OCR text. Without RapidOCR the list is empty.
    """
    import json

    if not _importable("rapidocr"):
        return []
    scale = float(cfg.get("scale", 2.0))
    folder = cache_dir(cfg)
    cached = folder / f"{hashlib.sha1(path.read_bytes()).hexdigest()}-{index}-lines-{scale}.json" if folder else None
    if cached and cached.exists():
        return [(tuple(box), text) for box, text in json.loads(cached.read_text(encoding="utf-8"))]
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            image = pdf[index].render(scale=scale).to_numpy()[..., :3].copy()
        finally:
            pdf.close()
    height, width = image.shape[:2]
    result = _rapidocr_engine("v5")(image)
    lines: list[tuple[Box, str]] = []
    for box, text in zip(list(result.boxes) if result.boxes is not None else [], list(result.txts or [])):
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        lines.append(((float(min(xs)) / width, float(min(ys)) / height, float(max(xs)) / width, float(max(ys)) / height), str(text)))
    if folder:
        folder.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(lines, ensure_ascii=False), encoding="utf-8")
    return lines


def _fold(text: str) -> tuple[str, list[int]]:
    """Lower-case letters and digits without diacritics, with the index of each kept character in the original."""
    import unicodedata

    out, where = [], []
    for i, ch in enumerate(text):
        base = unicodedata.normalize("NFKD", ch.lower().replace("ł", "l"))[:1]
        if base.isalnum():
            out.append(base)
            where.append(i)
    return "".join(out), where


def find_in_lines(lines: list[tuple[Box, str]], term: str, min_score: float = 0.8, word_end: bool = False) -> list[tuple[float, Box]]:
    """Boxes of a term in OCR lines as (score, box): exact matches ignoring case, diacritics and punctuation, else the
    best fuzzy match of at least min_score. The box covers the matched characters, estimated by their share of the line.
    With word_end the match is extended to the end of the word (inflected names)."""
    from difflib import SequenceMatcher

    needle, _ = _fold(term)
    if len(needle) < 3:
        return []
    found: list[tuple[float, Box]] = []
    fuzzy: tuple[float, Box] | None = None
    for (x0, y0, x1, y1), text in lines:
        hay, where = _fold(text)
        if not hay:
            continue

        def span(a: int, b: int) -> Box:
            start, end = where[a], where[b - 1] + 1
            if word_end:
                while end < len(text) and (text[end].isalpha() or text[end] == "-"):
                    end += 1
            return (x0 + (x1 - x0) * start / len(text), y0, x0 + (x1 - x0) * end / len(text), y1)

        at = hay.find(needle)
        while at >= 0:
            found.append((1.0, span(at, at + len(needle))))
            at = hay.find(needle, at + 1)
        if not found and len(needle) >= 6:
            matcher = SequenceMatcher(None, hay, needle, autojunk=False)
            blocks = [b for b in matcher.get_matching_blocks() if b.size]
            if blocks:
                score = sum(b.size for b in blocks) / len(needle)
                if score >= min_score and (fuzzy is None or score > fuzzy[0]):
                    fuzzy = (score, span(blocks[0].a, blocks[-1].a + blocks[-1].size))
    return found or ([fuzzy] if fuzzy else [])
