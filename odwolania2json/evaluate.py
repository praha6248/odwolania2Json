"""Field-level precision, recall and F1 against reference JSON files."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Score:
    """Confusion counts for a group of fields."""

    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        """Share of predicted values that are correct."""
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        """Share of reference values that were found."""
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall."""
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class Report:
    """Evaluation outcome with per-field breakdown and list of mismatches."""

    total: Score = field(default_factory=Score)
    per_field: dict[str, Score] = field(default_factory=lambda: defaultdict(Score))
    errors: list[tuple[str, str, Any, Any]] = field(default_factory=list)


def flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested JSON into a mapping of dotted paths to leaf values."""
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            out.update(flatten(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            out.update(flatten(value, f"{prefix}[{index}]"))
    else:
        out[prefix] = data
    return out


def same(a: Any, b: Any) -> bool:
    """Compare two leaf values leniently on whitespace, case and numeric type."""
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 0.005
    norm = lambda v: re.sub(r"\s+", " ", str(v)).strip().lower()
    return norm(a) == norm(b)


def compare(predicted: Any, expected: Any, report: Report, label: str) -> None:
    """Accumulate field-level confusion counts of one document into a report."""
    pred, gold = flatten(predicted or {}), flatten(expected)
    for path in sorted(set(pred) | set(gold)):
        key = re.sub(r"\[\d+\]", "[]", path)
        p, g = pred.get(path), gold.get(path)
        score = report.per_field[key]
        if p is None and g is None:
            continue
        if same(p, g):
            score.tp += 1
            report.total.tp += 1
            continue
        if p is not None:
            score.fp += 1
            report.total.fp += 1
        if g is not None:
            score.fn += 1
            report.total.fn += 1
        report.errors.append((label, path, p, g))


def evaluate_dataset(processor: Any, data_dir: str | Path, pairs: dict[str, str] | None = None) -> Report:
    """Run the processor on a training set laid out as <case>/<doc>.pdf next to <case>/<ref>.json."""
    pairs = pairs or {"odwolanie.pdf": "odwolanie.json", "pelnomocnictwo.pdf": "pelnomocnictwo.json", "potwierdzenie_przelewu.pdf": "przelew.json"}
    report = Report()
    for case in sorted(p for p in Path(data_dir).iterdir() if p.is_dir()):
        for pdf_name, json_name in pairs.items():
            pdf, ref = case / pdf_name, case / json_name
            if not (pdf.exists() and ref.exists()):
                continue
            result = processor.process_pdf(pdf)
            compare(result.data, json.loads(ref.read_text(encoding="utf-8")), report, f"{case.name}/{pdf_name}")
    return report


def format_report(report: Report, show_errors: int = 0) -> str:
    """Render a human readable summary table of a report."""
    lines = [f"{'field':55} {'P':>6} {'R':>6} {'F1':>6}  tp/fp/fn"]
    for key, s in sorted(report.per_field.items()):
        if s.tp + s.fp + s.fn:
            lines.append(f"{key:55} {s.precision:6.3f} {s.recall:6.3f} {s.f1:6.3f}  {s.tp}/{s.fp}/{s.fn}")
    t = report.total
    lines.append(f"{'TOTAL':55} {t.precision:6.3f} {t.recall:6.3f} {t.f1:6.3f}  {t.tp}/{t.fp}/{t.fn}")
    for label, path, p, g in report.errors[:show_errors]:
        lines.append(f"  {label} {path}\n      got: {p!r}\n      exp: {g!r}")
    return "\n".join(lines)
