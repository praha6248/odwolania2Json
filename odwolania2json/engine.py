"""Configuration driven field extraction engine with full provenance tracing."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import normalizers
from .config import DocumentType


@dataclass
class Evidence:
    """Where and how a value was found."""

    method: str
    snippet: str | None = None
    start: int | None = None
    end: int | None = None


@dataclass
class FieldResult:
    """Extracted value of a single configured field together with its evidence."""

    name: str
    value: Any
    evidence: Evidence | None = None
    source: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result for traces and the web UI."""
        ev = self.evidence
        return {
            "field": self.name,
            "value": self.value,
            "source": self.source,
            "method": ev.method if ev else None,
            "snippet": ev.snippet if ev else None,
            "start": ev.start if ev else None,
            "end": ev.end if ev else None,
        }


@dataclass
class Context:
    """State shared by extractors while processing one document."""

    text: str
    doc_type: DocumentType
    sections: dict[str, tuple[int, int]] = field(default_factory=dict)
    results: dict[str, FieldResult] = field(default_factory=dict)

    def scope(self, name: str | None) -> tuple[str, int]:
        """Return text of a named section (or whole text) and its offset in the document."""
        if not name:
            return self.text, 0
        names = [name] if isinstance(name, str) else list(name)
        for candidate in names:
            if candidate in self.sections:
                start, end = self.sections[candidate]
                return self.text[start:end], start
        return "", 0

    def value(self, name: str) -> Any:
        """Return the already extracted value of another field."""
        result = self.results.get(name)
        return result.value if result else None


Extractor = Callable[[Context, dict[str, Any]], tuple[Any, Evidence | None]]
_EXTRACTORS: dict[str, Extractor] = {}


def extractor(name: str) -> Callable[[Extractor], Extractor]:
    """Register a function as a named extractor usable from YAML configuration."""

    def wrap(func: Extractor) -> Extractor:
        _EXTRACTORS[name] = func
        return func

    return wrap


def available_extractors() -> list[str]:
    """Return the names of all registered extractors."""
    return sorted(_EXTRACTORS)


def snippet(text: str, start: int, end: int, pad: int = 60) -> str:
    """Return a short excerpt of text surrounding a span."""
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    return text[left:right].replace("\n", " ⏎ ")


def flags_of(spec: dict[str, Any]) -> int:
    """Build regex flags from a spec; matching is case-insensitive and multiline by default."""
    flags = re.M
    if spec.get("ignore_case", True):
        flags |= re.I
    if spec.get("dotall"):
        flags |= re.S
    return flags


def find_sections(text: str, doc_type: DocumentType) -> dict[str, tuple[int, int]]:
    """Locate configured sections, each delimited by a start regex and the nearest end regex."""
    found: dict[str, tuple[int, int]] = {}
    for name, spec in doc_type.sections.items():
        starts = spec["start"] if isinstance(spec["start"], list) else [spec["start"]]
        begin = None
        for pattern in starts:
            match = re.search(pattern, text, flags_of(spec))
            if match and (begin is None or match.start() < begin[0]):
                begin = (match.start(), match.end())
        if begin is None:
            continue
        from_pos = begin[0] if spec.get("include_start", False) else begin[1]
        end_pos = len(text)
        ends = spec.get("end") or []
        for pattern in ends if isinstance(ends, list) else [ends]:
            match = re.compile(pattern, flags_of(spec)).search(text, begin[1])
            if match and match.start() < end_pos:
                end_pos = match.start()
        max_chars = spec.get("max_chars")
        if max_chars:
            end_pos = min(end_pos, from_pos + int(max_chars))
        found[name] = (from_pos, end_pos)
    return found


@extractor("regex")
def extract_regex(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Return a capture group of the first (or n-th) match of a regex within a scope."""
    text, offset = ctx.scope(spec.get("scope"))
    pattern = spec["pattern"]
    group = spec.get("group", 1)
    matches = list(re.finditer(pattern, text, flags_of(spec)))
    if not matches:
        return None, None
    index = spec.get("occurrence", 0)
    if index >= len(matches) or -index > len(matches):
        return None, None
    match = matches[index]
    value = match.group(group) if match.re.groups >= (group if isinstance(group, int) else 1) else match.group(0)
    if value is None:
        return None, None
    start, end = match.span(group if match.re.groups else 0)
    return value, Evidence("regex", snippet(text, start, end), offset + start, offset + end)


SEPARATOR = r"(?![\wąćęłńóśźż])[ \t]*[:\-–.]*[ \t.]*"


def anchor(spec: dict[str, Any]) -> str:
    """Return the regex prefix anchoring a label at line start unless disabled in the spec."""
    return r"^[ \t]*" if spec.get("line_start", True) else r"(?<![\wąćęłńóśźż])"


@extractor("label")
def extract_label(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Return the value following one of several labels on the same or the next line."""
    text, offset = ctx.scope(spec.get("scope"))
    value_re = spec.get("value", r"[^\n]+")
    if spec.get("until"):
        for label in spec["labels"]:
            match = re.search(rf"{anchor(spec)}{label}{SEPARATOR}\n?", text, flags_of(spec))
            if not match:
                continue
            rest = text[match.end():]
            stop = re.search(spec["until"], rest, flags_of(spec))
            body = rest[: stop.start()] if stop else rest[: int(spec.get("max_chars", 400))]
            start = match.end()
            end = start + len(body)
            value = re.sub(r"\s*\n\s*", " ", body).strip()
            if value:
                return value, Evidence(f"label:{label}", snippet(text, start, end), offset + start, offset + end)
        return None, None
    for label in spec["labels"]:
        pattern = rf"{anchor(spec)}{label}{SEPARATOR}(?:\n[ \t]*)?({value_re})"
        match = re.search(pattern, text, flags_of(spec))
        if match:
            start, end = match.span(1)
            return match.group(1), Evidence(f"label:{label}", snippet(text, start, end), offset + start, offset + end)
    return None, None


@extractor("keyword_map")
def extract_keyword_map(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Choose an option whose keyword regex matches earliest (or with highest weight) in the scope."""
    text, offset = ctx.scope(spec.get("scope"))
    best: tuple[float, int, Any, re.Match[str]] | None = None
    for option in spec["options"]:
        for keyword in option.get("keywords", []):
            match = re.search(keyword, text, flags_of(spec))
            if not match:
                continue
            rank = (-float(option.get("priority", 0)), match.start())
            if best is None or rank < (best[0], best[1]):
                best = (rank[0], rank[1], option["value"], match)
    if best is None:
        return None, None
    match = best[3]
    return best[2], Evidence(f"keyword:{match.group(0)}", snippet(text, *match.span()), offset + match.start(), offset + match.end())


@extractor("map")
def extract_map(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Translate the value of another field through a lookup table."""
    source = ctx.value(spec["source"])
    if source is None:
        return None, None
    mapping = spec["mapping"]
    value = mapping.get(source, mapping.get(str(source)))
    return value, Evidence(f"map:{spec['source']}={source}")


@extractor("ref")
def extract_ref(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Copy the value of another field, optionally picking a key path inside it."""
    value = ctx.value(spec["source"])
    for key in spec.get("path", []):
        if value is None:
            break
        value = value[key] if isinstance(value, (list, dict)) else None
    return value, Evidence(f"ref:{spec['source']}")


@extractor("const")
def extract_const(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Return a constant value."""
    return spec.get("value"), Evidence("const")


@extractor("present")
def extract_present(ctx: Context, spec: dict[str, Any]) -> tuple[Any, Evidence | None]:
    """Return one value if another field is non-empty and another otherwise."""
    value = ctx.value(spec["source"])
    filled = value not in (None, "", [], {})
    return spec.get("yes", 1) if filled else spec.get("no", 0), Evidence(f"present:{spec['source']}")


def run_field(ctx: Context, name: str, spec: dict[str, Any]) -> FieldResult:
    """Run the chain of extractors configured for a field until one yields a value."""
    chain = spec.get("extract") or []
    if isinstance(chain, dict):
        chain = [chain]
    for step in chain:
        kind = step.get("type", "regex")
        if kind not in _EXTRACTORS:
            raise KeyError(f"{ctx.doc_type.name}.{name}: unknown extractor '{kind}'")
        raw, evidence = _EXTRACTORS[kind](ctx, step)
        value = normalizers.apply(step.get("normalize"), raw)
        value = normalizers.apply(spec.get("normalize"), value)
        if value not in (None, "", []):
            return FieldResult(name, value, evidence)
    return FieldResult(name, copy.deepcopy(spec.get("default")), None)


def render(template: Any, values: dict[str, Any]) -> Any:
    """Fill a template structure, replacing '$field' strings with extracted values."""
    if isinstance(template, dict):
        return {k: render(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, values) for v in template]
    if isinstance(template, str) and template.startswith("$"):
        return copy.deepcopy(values.get(template[1:]))
    return template


def extract(text: str, doc_type: DocumentType) -> tuple[dict[str, Any], Context]:
    """Extract all configured fields of a document and render its output JSON."""
    ctx = Context(text=text, doc_type=doc_type)
    ctx.sections = find_sections(text, doc_type)
    for name, spec in doc_type.fields.items():
        ctx.results[name] = run_field(ctx, name, spec or {})
    values = {name: result.value for name, result in ctx.results.items()}
    return render(doc_type.template, values), ctx
