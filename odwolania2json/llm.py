"""Optional refinement of rule-based results with an open-source LLM behind an OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Any

from . import normalizers
from .config import DocumentType
from .engine import Context, Evidence, FieldResult, is_derived, render, run_field

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

    def models(self) -> list[str]:
        """List model ids served by the endpoint."""
        request = urllib.request.Request(f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key or 'none'}"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return [m.get("id") for m in json.loads(response.read().decode()).get("data", [])]

    def check(self) -> dict[str, Any]:
        """Run a tiny extraction to verify connectivity, JSON mode and latency."""
        import time

        started = time.perf_counter()
        answer = self.chat(
            "Zwracasz wyłącznie JSON.",
            'Z tekstu "Odwołujący: Alfa sp. z o.o., NIP 1234567890" wyodrębnij {"nazwa": ..., "nip": ...}.',
        )
        return {"model": self.model, "seconds": round(time.perf_counter() - started, 2), "answer": json.loads(_strip_fences(answer))}

    def ask_fields(self, doc_type: DocumentType, text: str, targets: list[str]) -> dict[str, Any]:
        """Ask the model for the listed fields and return their normalized values (missing keys are None)."""
        hints = {}
        for name in targets:
            spec = doc_type.fields.get(name, {})
            hints[name] = spec.get("description", "") + (f" Przykład wartości: {spec['example']}" if spec.get("example") else "")
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
        answer = json.loads(_strip_fences(self.chat(system, user)))
        return {name: normalizers.apply(doc_type.fields.get(name, {}).get("normalize"), answer.get(name)) for name in targets}

    def verify(self, doc_type: DocumentType, text: str, data: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """Accurate mode: extract every LLM field independently, keep rule values, mark agreement and fill gaps."""
        from .evaluate import same

        targets = list(doc_type.llm.get("fields", []))
        if not targets:
            return data
        try:
            answers = self.ask_fields(doc_type, text, targets)
        except Exception as exc:
            log.warning("LLM verification failed: %s", exc)
            return data
        for name in targets:
            llm_value = answers.get(name)
            result = ctx.results.get(name)
            if result is None:
                continue
            result.llm_value = llm_value
            if result.value in (None, "", []):
                if llm_value not in (None, "", []):
                    ctx.results[name] = FieldResult(name, llm_value, Evidence("llm"), source="llm", review_context=result.review_context, llm_value=llm_value, llm_check="uzupełnione")
                continue
            agree = json.dumps(result.value, ensure_ascii=False, sort_keys=True) == json.dumps(llm_value, ensure_ascii=False, sort_keys=True) or (
                not isinstance(result.value, (list, dict)) and same(result.value, llm_value)
            )
            result.llm_check = "zgodne" if agree else "rozbieżne"
        for name, spec in doc_type.fields.items():
            if is_derived(spec):
                ctx.results[name] = run_field(ctx, name, spec)
        return render(doc_type.template, {name: result.value for name, result in ctx.results.items()})

    def refine(self, doc_type: DocumentType, text: str, data: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """Fast mode with LLM: ask the model only for fields left empty by the rules (listed in llm.fields)."""
        targets = [f for f in doc_type.llm.get("fields", []) if ctx.value(f) in (None, "", [])]
        if not targets:
            return data
        try:
            answers = self.ask_fields(doc_type, text, targets)
        except Exception as exc:
            log.warning("LLM refinement failed: %s", exc)
            return data
        for name in targets:
            value = answers.get(name)
            if value not in (None, "", []):
                ctx.results[name] = FieldResult(name, value, Evidence("llm"), source="llm", llm_value=value, llm_check="uzupełnione")
        for name, spec in doc_type.fields.items():
            if is_derived(spec) and ctx.value(name) in (None, "", []):
                ctx.results[name] = run_field(ctx, name, spec)
        return render(doc_type.template, {name: result.value for name, result in ctx.results.items()})


def _strip_fences(text: str) -> str:
    """Remove Markdown code fences that some models wrap around JSON."""
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
