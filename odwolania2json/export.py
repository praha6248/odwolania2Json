"""Tabular export of processed documents: an Excel workbook and a flat CSV file.

The workbook has a summary sheet, one sheet per document type with the output JSON flattened into columns
(lists are numbered, e.g. Odwolujacy[1].nazwa) and a sheet with the formal checks of every case.
"""

from __future__ import annotations

import csv
import io
from typing import Any

SUMMARY = ["plik", "typ", "postepowanie", "strona", "kompletnosc_pol", "czas_s", "zrodlo_tekstu"]
STATUS = {"ok": "OK", "warn": "Do sprawdzenia", "error": "Błąd", "skip": "Nie sprawdzono"}


def flatten(value: Any, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    """Flatten nested JSON into 'a.b[1].c' columns."""
    out = {} if out is None else out
    if isinstance(value, dict):
        for key, item in value.items():
            flatten(item, f"{prefix}.{key}" if prefix else key, out)
    elif isinstance(value, list):
        if not value:
            out[prefix] = ""
        for index, item in enumerate(value, 1):
            flatten(item, f"{prefix}[{index}]", out)
    else:
        out[prefix] = value
    return out


def completeness(doc: dict[str, Any]) -> float | None:
    """Share of filled leaves in the output JSON, as shown in the document table."""
    if not doc.get("data"):
        return None
    leaves = list(flatten(doc["data"]).values())
    return round(sum(v not in (None, "") for v in leaves) / len(leaves), 3) if leaves else 0.0


def summary_row(doc: dict[str, Any]) -> dict[str, Any]:
    """One summary row of a document."""
    case = doc.get("case_values") or {}
    return {
        "plik": doc.get("filename"),
        "typ": doc.get("doc_label"),
        "postepowanie": case.get("reference") or "",
        "strona": ", ".join(case.get("party") or []),
        "kompletnosc_pol": completeness(doc),
        "czas_s": doc.get("seconds"),
        "zrodlo_tekstu": "OCR" if doc.get("ocr") else "warstwa tekstowa",
    }


def columns(rows: list[dict[str, Any]], first: list[str]) -> list[str]:
    """Column order: the given first columns, then the others in order of appearance."""
    seen = dict.fromkeys(first)
    for row in rows:
        for key in row:
            seen.setdefault(key)
    return list(seen)


def to_csv(documents: list[dict[str, Any]]) -> bytes:
    """One row per document with the summary and every flattened output field; UTF-8 with BOM and ';' for Excel."""
    rows = [{**summary_row(d), **flatten(d.get("data") or {})} for d in documents]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns(rows, SUMMARY), delimiter=";", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def to_xlsx(documents: list[dict[str, Any]], cases: list[dict[str, Any]], labels: dict[str, str]) -> bytes:
    """Excel workbook with a summary, one sheet per document type and the formal checks."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    book = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="F04E23")

    def sheet(title: str, rows: list[dict[str, Any]], first: list[str]) -> None:
        """Write rows to a new sheet with a styled, frozen header and fitted column widths."""
        ws = book.create_sheet(title[:31])
        names = columns(rows, first)
        ws.append(names)
        for row in rows:
            ws.append([row.get(n) for n in names])
        for cell in ws[1]:
            cell.font, cell.fill = header_font, header_fill
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for index, name in enumerate(names, 1):
            width = max([len(str(name))] + [len(str(r.get(name) or "")) for r in rows])
            ws.column_dimensions[get_column_letter(index)].width = min(60, max(10, width + 2))

    book.remove(book.active)
    sheet("Dokumenty", [summary_row(d) for d in documents], SUMMARY)
    for doc_type in sorted({d["doc_type"] for d in documents if d.get("doc_type")}):
        sheet(labels.get(doc_type, doc_type), [{"plik": d["filename"], **flatten(d.get("data") or {})} for d in documents if d.get("doc_type") == doc_type], ["plik"])
    checks = [
        {"postepowanie": c.get("reference"), "kontrola": k["label"], "wynik": STATUS.get(k["status"], k["status"]), "szczegoly": k["detail"]}
        for c in cases for k in c.get("checks") or []
    ]
    if checks:
        sheet("Kontrola formalna", checks, ["postepowanie", "kontrola", "wynik", "szczegoly"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
