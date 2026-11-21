"""Keyword based document classification driven by configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import DocumentType, Settings
from .pdftext import compact


@dataclass
class Classification:
    """Result of classifying a document, including scores of all candidate types."""

    doc_type: str | None
    score: float
    scores: dict[str, float] = field(default_factory=dict)
    matched: dict[str, list[str]] = field(default_factory=dict)


def score_type(doc_type: DocumentType, text: str, filename: str) -> tuple[float, list[str]]:
    """Score how well a text matches a document type using weighted keywords."""
    cfg = doc_type.classify
    head = compact(text[: int(cfg.get("head_chars", 2000))])
    whole = compact(text)
    score = 0.0
    hits: list[str] = []
    for keyword, weight in (cfg.get("head_keywords") or {}).items():
        if compact(keyword) in head:
            score += float(weight)
            hits.append(keyword)
    for keyword, weight in (cfg.get("keywords") or {}).items():
        if compact(keyword) in whole:
            score += float(weight)
            hits.append(keyword)
    for pattern, weight in (cfg.get("patterns") or {}).items():
        if re.search(pattern, text, flags=re.I | re.M):
            score += float(weight)
            hits.append(pattern)
    name = compact(Path(filename).stem)
    for hint, weight in (cfg.get("filename_hints") or {}).items():
        if compact(hint) in name:
            score += float(weight)
            hits.append(f"filename:{hint}")
    return score, hits


def classify(settings: Settings, text: str, filename: str = "") -> Classification:
    """Pick the best matching document type, or None when nothing passes the threshold."""
    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}
    for doc_type in settings.document_types:
        scores[doc_type.name], matched[doc_type.name] = score_type(doc_type, text, filename)
    if not scores:
        return Classification(None, 0.0)
    best = max(scores, key=lambda k: scores[k])
    if scores[best] < settings.min_classification_score:
        return Classification(None, scores[best], scores, matched)
    return Classification(best, scores[best], scores, matched)
