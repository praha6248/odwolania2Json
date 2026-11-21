"""Optional refinement of rule-based results with an open-source LLM behind an OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Any

from .config import DocumentType
from .engine import Context, Evidence, FieldResult

log = logging.getLogger("odwolania2json.llm")


class LLMClient:
    """Minimal client for OpenAI-compatible chat completion endpoints such as Ollama, vLLM or llama.cpp."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Store connection settings."""
        self.base_url = str(cfg.get("base_url", "http://localhost:11434/v1")).rstrip("/")
        self.model = cfg.get("model", "qwen2.5:7b-instruct")
        self.api_key = cfg.get("api_key", "")
        self.timeout = float(cfg.get("timeout", 120))
        self.max_chars = int(cfg.get("max_chars", 12000))

    def chat(self, system: str, user: str) -> str:
        """Send a chat completion request and return the assistant message content."""
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key or 'none'}"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode())
        return payload["choices"][0]["message"]["content"]

    def refine(self, doc_type: DocumentType, text: str, data: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """Ask the model to fill only fields left empty by the rules for those listed in the type's llm.fields."""
        targets = [f for f in doc_type.llm.get("fields", []) if ctx.value(f) in (None, "", [])]
        if not targets:
            return data
        hints = {f: doc_type.fields.get(f, {}).get("description", "") for f in targets}
        system = doc_type.llm.get(
            "system",
            "Jesteś precyzyjnym systemem ekstrakcji danych z polskich dokumentów prawnych. "
            "Zwracasz wyłącznie JSON. Jeśli informacji nie ma w tekście, zwróć null.",
        )
        user = (
            f"Typ dokumentu: {doc_type.label}\nPola do uzupełnienia (nazwa: opis):\n"
            + json.dumps(hints, ensure_ascii=False, indent=1)
            + "\n\nTekst dokumentu:\n"
            + text[: self.max_chars]
        )
        try:
            answer = json.loads(_strip_fences(self.chat(system, user)))
        except Exception as exc:
            log.warning("LLM refinement failed: %s", exc)
            return data
        values = {name: result.value for name, result in ctx.results.items()}
        for name in targets:
            value = answer.get(name)
            if value in (None, "", []):
                continue
            ctx.results[name] = FieldResult(name, value, Evidence("llm"), source="llm")
            values[name] = value
        from .engine import render

        return render(doc_type.template, values)


def _strip_fences(text: str) -> str:
    """Remove Markdown code fences that some models wrap around JSON."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
