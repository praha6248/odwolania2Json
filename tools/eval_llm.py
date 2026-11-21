"""Measure what open LLMs extract on their own (rules only classify the document; every llm.fields value comes from the model).

Usage:
    python tools/eval_llm.py --url http://100.89.78.124:11434/v1 --data data_train --cases 10 \
        --models hf.co/speakleash/Bielik-4.5B-v3.0-Instruct-GGUF:Q8_0 local/qwen3-1.7b

Prints per-model precision, recall, F1 and mean seconds per document, and writes a JSON summary next to --out.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from odwolania2json.classifier import classify  # noqa: E402
from odwolania2json.config import load_settings  # noqa: E402
from odwolania2json.engine import extract  # noqa: E402
from odwolania2json.evaluate import Report, compare  # noqa: E402
from odwolania2json.llm import LLMClient  # noqa: E402
from odwolania2json.pdftext import extract_text  # noqa: E402

PAIRS = {"odwolanie.pdf": "odwolanie.json", "pelnomocnictwo.pdf": "pelnomocnictwo.json", "potwierdzenie_przelewu.pdf": "przelew.json"}


def run_model(model: str, url: str, cases: list[Path], settings, api_key: str = "") -> dict:
    """Evaluate one model in LLM-only mode on the given case folders."""
    client = LLMClient({**settings.llm, "base_url": url, "model": model, "api_key": api_key, "timeout": 300})
    report = Report()
    seconds = []
    failures = 0
    for case in cases:
        for pdf_name, json_name in PAIRS.items():
            pdf, ref = case / pdf_name, case / json_name
            if not (pdf.exists() and ref.exists()):
                continue
            text = extract_text(pdf, {"enabled": False}).text
            doc_type = settings.get_type(classify(settings, text, pdf.name).doc_type or "")
            if doc_type is None:
                compare(None, json.loads(ref.read_text(encoding="utf-8")), report, f"{case.name}/{pdf_name}")
                continue
            _, ctx = extract(text, doc_type)
            ctx.results = {}
            started = time.perf_counter()
            try:
                data = client.refine(doc_type, text, {}, ctx)
            except Exception:
                data, failures = None, failures + 1
            seconds.append(time.perf_counter() - started)
            compare(data, json.loads(ref.read_text(encoding="utf-8")), report, f"{case.name}/{pdf_name}")
    t = report.total
    return {
        "model": model,
        "precision": round(t.precision, 4),
        "recall": round(t.recall, 4),
        "f1": round(t.f1, 4),
        "documents": len(seconds),
        "seconds_per_document": round(sum(seconds) / max(1, len(seconds)), 2),
        "failures": failures,
        "per_field": {k: round(v.f1, 3) for k, v in sorted(report.per_field.items()) if v.tp + v.fp + v.fn},
    }


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark for every requested model."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--data", type=Path, action="append", required=True)
    parser.add_argument("--cases", type=int, default=10, help="cases per data folder")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--out", type=Path, default=Path("llm_benchmark.json"))
    args = parser.parse_args(argv)
    settings = load_settings()
    cases = [c for folder in args.data for c in sorted(p for p in folder.iterdir() if p.is_dir() and any((p / j).exists() for j in PAIRS.values()))[: args.cases]]
    results = []
    for model in args.models:
        result = run_model(model, args.url, cases, settings, args.api_key)
        results.append(result)
        print(f"{model:60} F1 {result['f1']:.3f}  P {result['precision']:.3f}  R {result['recall']:.3f}  {result['seconds_per_document']:6.2f} s/doc  failures {result['failures']}", flush=True)
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
