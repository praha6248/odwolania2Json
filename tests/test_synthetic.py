"""Generated edge-case cases (unseen layouts and phrasing) must be extracted with near-perfect F1."""

import importlib.util
import sys
from pathlib import Path

import pytest

from odwolania2json.config import load_settings
from odwolania2json.evaluate import evaluate_dataset
from odwolania2json.pipeline import Processor

ROOT = Path(__file__).resolve().parents[1]
pytest.importorskip("reportlab")


def generator():
    """Import tools/generate_testset.py as a module."""
    spec = importlib.util.spec_from_file_location("generate_testset", ROOT / "tools" / "generate_testset.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_testset"] = module
    spec.loader.exec_module(module)
    return module


def test_generated_cases_and_negatives(tmp_path):
    """Twenty fresh synthetic cases reach F1 >= 0.99 and look-alike documents stay unclassified."""
    module = generator()
    try:
        module.main(["--cases", "20", "--seed", "99", "--out", str(tmp_path)])
    except SystemExit as exc:
        if "DejaVuSans" in str(exc):
            pytest.skip("font not available")
        raise
    settings = load_settings()
    settings.ocr["enabled"] = False
    processor = Processor(settings, use_llm=False)
    report = evaluate_dataset(processor, tmp_path / "cases", fuzzy=False)
    assert report.total.f1 >= 0.99, report.errors[:10]
    for pdf in (tmp_path / "negatives").glob("*.pdf"):
        assert processor.process_pdf(pdf).doc_type is None, pdf.name
