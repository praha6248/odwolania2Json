"""Accurate-mode assistant: document summaries and questions over all uploaded documents (retrieval-augmented).

Retrieval uses BM25 over overlapping text chunks with accent-insensitive tokens and light suffix stripping for Polish
inflection, so it runs on CPU without an embedding model. The LLM answers only from the retrieved fragments and cites
them, which keeps answers checkable against the source documents.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .fuzzy_re import fold
from .llm import LLMClient, _strip_fences

WORD = re.compile(r"[0-9a-z]+")
STOPWORDS = {"i", "w", "z", "na", "do", "o", "oraz", "sie", "nie", "jest", "to", "ze", "od", "po", "dla", "przez", "a", "lub", "jak", "co", "czy", "jaki", "jaka", "jakie", "ktory", "ktora", "ktore", "kto", "kiedy", "gdzie", "ile", "jakiej", "jakim", "jaka", "jak"}


SUFFIXES = sorted(["ach", "ami", "ego", "emu", "ych", "ymi", "owi", "ow", "om", "ie", "ia", "iu", "ej", "a", "e", "i", "o", "u", "y"], key=len, reverse=True)


def stem(word: str) -> str:
    """Strip a common Polish inflectional ending and keep a five-character prefix."""
    if word.isdigit():
        return word
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:5]


def tokens(text: str) -> list[str]:
    """Lowercase, accent-free, stemmed tokens without stop words."""
    return [stem(word) for word in WORD.findall(fold(text).lower()) if word not in STOPWORDS and len(word) >= 2]


@dataclass
class Chunk:
    """A retrievable fragment of one document."""

    doc_id: str
    filename: str
    start: int
    text: str


def chunk_text(doc_id: str, filename: str, text: str, size: int = 900, overlap: int = 200) -> list[Chunk]:
    """Split a document into overlapping fragments aligned to line breaks where possible."""
    chunks = []
    position = 0
    while position < len(text):
        end = min(len(text), position + size)
        if end < len(text):
            newline = text.rfind("\n", position + size // 2, end)
            end = newline if newline > position else end
        chunks.append(Chunk(doc_id, filename, position, text[position:end]))
        if end >= len(text):
            break
        position = max(end - overlap, position + 1)
    return chunks


class BM25:
    """Okapi BM25 ranking over chunks."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75) -> None:
        """Index the chunks."""
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [Counter(tokens(c.text)) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lengths) / max(1, len(self.lengths))
        df: Counter[str] = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 6) -> list[tuple[float, Chunk]]:
        """Return the k best chunks with their scores."""
        terms = tokens(query)
        scored = []
        for doc, length, chunk in zip(self.docs, self.lengths, self.chunks):
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf:
                    score += self.idf[term] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg))
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: -item[0])
        return scored[:k]


def build_index(documents: list[dict[str, Any]]) -> BM25:
    """Index documents given as dicts with id, filename and text."""
    chunks = [c for d in documents for c in chunk_text(d["id"], d["filename"], d.get("text") or "")]
    return BM25(chunks)


def ask(client: LLMClient, question: str, documents: list[dict[str, Any]], k: int = 6) -> dict[str, Any]:
    """Answer a question from the most relevant fragments of the documents, citing them by number."""
    hits = build_index(documents).search(question, k)
    if not hits:
        return {"answer": "Nie znalazłem w dokumentach fragmentów związanych z pytaniem.", "sources": []}
    context = "\n\n".join(f"[{i}] ({c.filename})\n{c.text.strip()}" for i, (_, c) in enumerate(hits, 1))
    system = (
        "Jesteś asystentem analizującym dokumenty postępowania odwoławczego przed KIO. Odpowiadasz po polsku, "
        "wyłącznie na podstawie podanych fragmentów. Jeśli odpowiedzi nie ma we fragmentach, napisz to wprost. "
        'Zwróć JSON: {"answer": "odpowiedź z odwołaniami [n]", "cited": [numery użytych fragmentów]}.'
    )
    raw = client.chat(system, f"Fragmenty:\n{context}\n\nPytanie: {question}")
    try:
        parsed = json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
        parsed = {"answer": raw.strip(), "cited": []}
    cited = [int(n) for n in parsed.get("cited") or [] if str(n).isdigit() and 1 <= int(n) <= len(hits)] or list(range(1, min(3, len(hits)) + 1))
    sources = []
    for n in cited:
        chunk = hits[n - 1][1]
        sources.append({"n": n, "doc_id": chunk.doc_id, "filename": chunk.filename, "start": chunk.start, "end": chunk.start + len(chunk.text), "snippet": chunk.text.strip()[:400]})
    return {"answer": str(parsed.get("answer") or "").strip(), "sources": sources}


def summarize(client: LLMClient, document: dict[str, Any], max_chars: int = 12000) -> dict[str, Any]:
    """Summarize one document: what it is about, key parties, claims or requests, and dates."""
    system = (
        "Jesteś asystentem prawnym. Streszczasz polskie dokumenty z postępowań odwoławczych przed KIO rzeczowo i krótko. "
        'Zwróć JSON: {"streszczenie": "2-4 zdania", "kluczowe_punkty": ["..."], "terminy_i_kwoty": ["..."]}. '
        "Nie dodawaj informacji, których nie ma w tekście."
    )
    raw = client.chat(system, f"Typ: {document.get('doc_label', '')}\nPlik: {document['filename']}\n\nTekst:\n{(document.get('text') or '')[:max_chars]}")
    try:
        parsed = json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
        parsed = {"streszczenie": raw.strip()}
    return {
        "summary": str(parsed.get("streszczenie") or "").strip(),
        "points": [str(p) for p in parsed.get("kluczowe_punkty") or []][:8],
        "facts": [str(p) for p in parsed.get("terminy_i_kwoty") or []][:8],
    }
