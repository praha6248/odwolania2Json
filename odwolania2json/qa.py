"""Answers to typical questions without a language model, configured in config/assistant.yaml.

The question is matched to an intent by keywords; the answer is filled in from the extracted JSON of the uploaded
documents, one line per document, and lists the source fragments of the fields it uses. Because it reads the same
values as the output JSON, the answer can never contradict the extraction.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import yaml

from . import fuzzy_re as fx
from .cases import key
from .formal import walk

PLACEHOLDER = re.compile(r"\{([^{}|]+)(?:\|(\w+))?\}")
MISSING = "—"


def load_intents(config_dir: Path) -> list[dict[str, Any]]:
    """Read the intents from config_dir/assistant.yaml (none when the file is missing).

    The search_only words are attached to every intent as a veto, so a single list travels with the intents.
    """
    path = config_dir / "assistant.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    veto = list(raw.get("search_only") or [])
    return [{**intent, "veto": veto} for intent in raw.get("intents") or []]


def pick_intent(question: str, intents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The intent with the most keywords found in the question (ties go to the one listed first); None for questions about the content of a letter."""
    best, best_hits = None, 0
    if intents and any(fx.search(pattern, question, re.I) for pattern in intents[0].get("veto") or []):
        return None
    for intent in intents:
        hits = sum(1 for pattern in intent.get("keywords") or [] if fx.search(pattern, question, re.I))
        if hits > best_hits:
            best, best_hits = intent, hits
    return best


def show(value: Any, style: str | None) -> str:
    """Format one value for an answer."""
    if style == "zl" and isinstance(value, (int, float)):
        return f"{value:,.2f} zł".replace(",", " ").replace(".", ",")
    if style == "data":
        try:
            return dt.date.fromisoformat(str(value)).strftime("%d.%m.%Y")
        except ValueError:
            return str(value)
    return str(value)


def fill(template: str, data: dict[str, Any]) -> tuple[str, bool]:
    """Fill a template from output JSON; also say whether any placeholder had a value."""
    found = False

    def replace(match: re.Match[str]) -> str:
        nonlocal found
        values = [v for v in walk(data, match.group(1).split(".")) if v not in (None, "", [], {})]
        found = found or bool(values)
        return ", ".join(show(v, match.group(2)) for v in values) if values else MISSING

    return PLACEHOLDER.sub(replace, template), found


def answer(question: str, documents: list[dict[str, Any]], intents: list[dict[str, Any]]) -> dict[str, Any]:
    """Answer a typical question from the documents' JSON, or return answer None when no intent matches."""
    intent = pick_intent(question, intents)
    if intent is None:
        return {"answer": None, "intent": None, "sources": []}
    asked = key(question)
    mentioned = {key((d.get("case_values") or {}).get("reference")) for d in documents}
    mentioned = {ref for ref in mentioned if ref and ref in asked}
    if mentioned:
        documents = [d for d in documents if key((d.get("case_values") or {}).get("reference")) in mentioned]
    lines, sources = [], []
    for rule in intent.get("answers") or []:
        for doc in documents:
            if doc.get("doc_type") != rule.get("type") or not doc.get("data"):
                continue
            text, found = fill(rule["text"], doc["data"])
            if not found:
                continue
            reference = (doc.get("case_values") or {}).get("reference")
            lines.append(f"{reference} · {doc['filename']}: {text}" if reference else f"{doc['filename']}: {text}")
            for field in doc.get("fields") or []:
                if field["field"] in (rule.get("sources") or []) and field.get("start") is not None:
                    sources.append({
                        "n": len(sources) + 1,
                        "doc_id": doc["id"],
                        "filename": doc["filename"],
                        "field": field["field"],
                        "start": field["start"],
                        "end": field["end"],
                        "snippet": (field.get("snippet") or "").strip(),
                    })
    if not lines:
        return {"answer": None, "intent": intent.get("id"), "sources": []}
    return {"answer": "\n".join(lines), "intent": intent.get("id"), "sources": sources[:8]}
