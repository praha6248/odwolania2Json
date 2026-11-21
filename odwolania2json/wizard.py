"""Building a new document type from a sample document: rule suggestions, live preview and saving to YAML.

A field is defined by selecting its value in the sample text. The value's shape (date, amount, account, identifier,
e-mail, free text) gives the value pattern and normalizer; the text before it on the same line, or the line above,
becomes the label. The draft has the same structure as a YAML file in config/document_types, so a saved type is
an ordinary configuration file that can be edited later by hand.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .classifier import score_type
from .config import DocumentType, document_type_from_dict
from .engine import extract
from .fuzzy_re import fold

SHAPES: list[tuple[str, str, list[str], str]] = [
    ("data", r"\d{1,2}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{4}|\d{4}-\d{2}-\d{2}", ["date_iso"], r"\d{1,2}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{4}|\d{4}-\d{2}-\d{2}"),
    ("data", r"\d{1,2}\s+[a-ząćęłńóśźż]+\s+\d{4}(?:\s*r\.?)?", ["date_iso"], r"\d{1,2}\s+[a-ząćęłńóśźż]+\s+\d{4}"),
    ("rachunek", r"(?:PL)?\s*\d{2}(?:\s?\d{4}){6}", ["account"], r"(?:PL)?\s*\d{2}(?:[ \t]?\d{4}){6}"),
    ("kwota", r"\d[\d  .]*,\d{2}(?:\s*(?:zł|PLN))?|\d[\d  ]*(?:\.\d{2})?\s*(?:zł|PLN)", ["amount"], r"\d[\d  .]*(?:,\d{2})?(?=\s*(?:zł|PLN)|\b)"),
    ("email", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", ["strip"], r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    ("numer", r"\d[\d\- ]{5,}\d", ["digits"], r"\d[\d\- ]{5,}\d"),
    ("osoba", r"[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:-[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:-[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?", ["person_name"], r"[A-ZĄĆĘŁŃÓŚŹŻ][\w-]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][\w-]+"),
    ("sygnatura", r"[A-ZĄĆĘŁŃÓŚŹŻ]{1,6}[.\s/-]*\d[\w./-]*", ["strip"], r"[A-ZĄĆĘŁŃÓŚŹŻ]{1,6}[.\s/-]*\d[\w./-]*"),
]
STOPWORDS = {"oraz", "który", "która", "które", "przez", "dnia", "roku", "tego", "jest", "jako", "postępowania", "wraz", "zgodnie", "niniejszym", "przed"}


def slug(text: str) -> str:
    """Identifier made of lowercase ASCII letters, digits and underscores."""
    ascii_text = unicodedata.normalize("NFKD", fold(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")[:40] or "pole"


def shape(value: str) -> tuple[str, list[str], str]:
    """Guess the kind of a value: suggested field name, normalizers and a general value pattern."""
    for name, test, normalize, pattern in SHAPES:
        if re.fullmatch(test, value.strip(), re.IGNORECASE):
            return name, normalize, pattern
    return "tekst", ["strip"], r"[^\n]+"


def label_pattern(label: str) -> str:
    """Regex for a label: escaped words joined by flexible whitespace, without trailing separators."""
    words = re.sub(r"[\s:.\-–]+$", "", label.strip()).split()
    return r"\s+".join(re.escape(w) for w in words)


def previous_line(text: str, line_start: int, max_blank: int = 3) -> tuple[str, int]:
    """The nearest non-empty line above a position and the number of blank lines in between."""
    lines = text[:max(0, line_start - 1)].split("\n")
    gap = 0
    while lines and not lines[-1].strip() and gap <= max_blank:
        lines.pop()
        gap += 1
    return (lines[-1].strip() if lines else ""), gap


def is_label(text: str) -> bool:
    """Tell whether text before a value looks like a caption: short, wordy and not itself a value."""
    words = re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{3,}", text)
    return bool(text) and len(text) <= 60 and bool(words) and shape(text.split()[-1])[0] in {"tekst"} and sum(c.isdigit() for c in text) <= len(text) // 4


def suggest_field(text: str, start: int, end: int) -> dict[str, Any]:
    """Suggest a field definition for the selected value text[start:end]."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    value = text[start:end]
    if not value:
        raise ValueError("Zaznacz wartość w tekście dokumentu.")
    kind, normalize, value_re = shape(value)
    if "\n" in value:
        value_re, normalize = r"[^\n]+", ["strip"]
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start].strip()
    previous, gap = previous_line(text, line_start)
    label = ""
    spec: dict[str, Any]
    if is_label(prefix):
        label = " ".join(prefix.split()[-4:])
        spec = {"type": "label", "labels": [label_pattern(label)], "value": value_re, "line_start": label == prefix}
    elif not prefix and is_label(previous) and gap == 0:
        label = previous
        spec = {"type": "label", "labels": [label_pattern(previous)], "value": value_re}
    elif not prefix and is_label(previous):
        label = previous
        spec = {"type": "regex", "pattern": rf"^[ \t]*{label_pattern(previous)}[ \t]*[:\-]?[ \t]*\n(?:[ \t]*\n){{0,3}}[ \t]*({value_re})"}
    else:
        occurrence = sum(1 for m in re.finditer(value_re, text[:start], re.IGNORECASE | re.MULTILINE) if m.group(0).strip())
        spec = {"type": "regex", "pattern": f"({value_re})", "occurrence": occurrence}
    if "\n" in value:
        spec = {"type": "label", "labels": spec.get("labels") or [label_pattern(label or value.split()[0])], "until": r"\n\s*\n", "line_start": spec.get("line_start", True)}
    name = slug(label) if label else kind
    return {"name": name, "value": value, "field": {"description": f"Wartość po „{label}”." if label else f"Pole typu {kind}.", "example": value, "normalize": normalize, "extract": [spec]}}


def suggest_keywords(text: str, limit: int = 3) -> dict[str, Any]:
    """Suggest classification keywords: the title line near the top (weight 5) and frequent longer words (weight 1)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()][:8]
    candidates = [line for line in lines if not re.search(r"\d", line) and ":" not in line and (2 <= len(line.split()) <= 8 or (line.isupper() and len(line) >= 4))]
    head = {}
    if candidates:
        for title in sorted(candidates, key=lambda line: (not line.isupper(), -len(line)))[:2]:
            head[title.lower()] = 5 if not head else 2
    counts = Counter(w.lower() for w in re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{7,}", text) if w.lower() not in STOPWORDS)
    keywords = {w: 1 for w, _ in counts.most_common(limit + 3) if not any(w in h for h in head)}
    return {"head_keywords": head, "keywords": dict(list(keywords.items())[:limit])}


def build(draft: dict[str, Any]) -> dict[str, Any]:
    """Complete a draft into a YAML structure of a document type."""
    name = slug(draft.get("name") or draft.get("label") or "nowy_typ")
    fields = {slug(k): v for k, v in (draft.get("fields") or {}).items()}
    classify = dict(draft.get("classify") or {})
    classify.setdefault("head_chars", 800)
    return {
        "name": name,
        "label": draft.get("label") or name,
        "description": draft.get("description") or "Typ utworzony w kreatorze.",
        "classify": classify,
        "fields": fields,
        "template": draft.get("template") or {f: f"${f}" for f in fields},
    }


def compile_type(draft: dict[str, Any]) -> DocumentType:
    """Turn a draft into a document type object."""
    return document_type_from_dict(build(draft))


def preview(draft: dict[str, Any], text: str, filename: str = "", samples: list[dict[str, Any]] | None = None, threshold: float = 3.0) -> dict[str, Any]:
    """Run a draft type on the sample text and score it against the other uploaded documents."""
    doc_type = compile_type(draft)
    data, ctx = extract(text, doc_type)
    score, hits = score_type(doc_type, text, filename)
    matches = []
    for sample in samples or []:
        sample_text = sample.get("text") or ""
        sample_score, _ = score_type(doc_type, sample_text, sample.get("filename") or "")
        current = float((sample.get("classification") or {}).get("score") or 0) if sample.get("doc_type") else 0.0
        item = {"id": sample["id"], "filename": sample["filename"], "doc_type": sample.get("doc_type"), "doc_label": sample.get("doc_label"), "score": sample_score, "current_score": current, "matches": sample_score >= threshold and sample_score >= current}
        if item["matches"]:
            _, sample_ctx = extract(sample_text, doc_type)
            item["filled"] = sum(r.value not in (None, "", [], {}) for r in sample_ctx.results.values())
        matches.append(item)
    return {
        "yaml": yaml.safe_dump(build(draft), allow_unicode=True, sort_keys=False, width=120),
        "data": data,
        "fields": [r.to_dict() for r in ctx.results.values()],
        "score": score,
        "hits": hits,
        "recognized": score >= threshold,
        "samples": matches,
        "field_count": len(doc_type.fields),
    }


def save(draft: dict[str, Any], config_dir: Path, overwrite: bool = False) -> Path:
    """Write the type to config_dir/document_types/<name>.yaml."""
    data = build(draft)
    if not data["fields"]:
        raise ValueError("Dodaj co najmniej jedno pole.")
    compile_type(draft)
    path = config_dir / "document_types" / f"{data['name']}.yaml"
    if path.exists() and not overwrite:
        raise FileExistsError(f"Typ {data['name']} już istnieje.")
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Created with the document type wizard; edit freely, see docs/nowy-typ-dokumentu.md\n"
    path.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return path
