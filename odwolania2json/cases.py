"""Grouping of uploaded documents into cases and consistency checks, driven by the 'case' section of each type."""

from __future__ import annotations

import re
from typing import Any

from .fuzzy_re import fold


def resolve(values: dict[str, Any], path: str | None) -> list[Any]:
    """Resolve a path such as 'mocodawca[].data.nazwa' against extracted field values, returning all leaves."""
    if not path:
        return []
    parts = path.split(".")
    head = parts[0]
    nodes = [values.get(head.removesuffix("[]"))]
    if head.endswith("[]"):
        nodes = [item for node in nodes for item in (node or [])]
    for part in parts[1:]:
        key = part.removesuffix("[]")
        nodes = [node.get(key) if isinstance(node, dict) else None for node in nodes]
        if part.endswith("[]"):
            nodes = [item for node in nodes for item in (node or [])]
    return [node for node in nodes if node not in (None, "", [])]


def case_values(case_spec: dict[str, str], values: dict[str, Any]) -> dict[str, Any]:
    """Return the party names and procurement reference that identify the case of one document."""
    references = resolve(values, case_spec.get("reference"))
    return {"party": [str(p) for p in resolve(values, case_spec.get("party"))], "reference": str(references[0]) if references else None}


def key(text: str | None) -> str:
    """Comparison key: accent-free, lowercase, without spaces and punctuation."""
    return re.sub(r"[\W_]+", "", fold(text or "").lower())


def group_cases(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group documents by procurement reference and report whether their parties agree."""
    groups: dict[str, dict[str, Any]] = {}
    loose = []
    for doc in documents:
        values = doc.get("case_values") or {}
        reference = values.get("reference")
        if not doc.get("doc_type"):
            continue
        if not reference:
            loose.append(doc)
            continue
        group = groups.setdefault(key(reference), {"reference": reference, "documents": []})
        group["documents"].append(doc)
    out = []
    for group in groups.values():
        party_sets = [{key(p) for p in d["case_values"].get("party") or []} for d in group["documents"]]
        common = set.intersection(*[s for s in party_sets if s]) if any(party_sets) else set()
        members = []
        for doc, parties in zip(group["documents"], party_sets):
            status = "brak" if not parties else ("zgodne" if parties & common or len([s for s in party_sets if s]) == 1 else "rozbieżne")
            members.append({"id": doc["id"], "filename": doc["filename"], "doc_type": doc["doc_type"], "doc_label": doc.get("doc_label"), "party": doc["case_values"].get("party"), "status": status})
        types = {m["doc_type"] for m in members}
        out.append({
            "reference": group["reference"],
            "documents": members,
            "consistent": all(m["status"] != "rozbieżne" for m in members),
            "missing_types": sorted({"odwolanie", "pelnomocnictwo", "przelew"} - types),
        })
    out.sort(key=lambda g: g["reference"])
    if loose:
        out.append({"reference": None, "documents": [{"id": d["id"], "filename": d["filename"], "doc_type": d["doc_type"], "doc_label": d.get("doc_label"), "party": (d.get("case_values") or {}).get("party"), "status": "bez numeru"} for d in loose], "consistent": True, "missing_types": []})
    return out
