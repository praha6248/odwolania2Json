"""Prepare the evaluation VM: download every OCR model now and check the pipeline on a text PDF and a scan.

Run once by setup.sh. Builds an image-only copy of a sample transfer confirmation, processes it together with the
text PDFs of a fixture case and fails loudly when an output JSON is missing or the scan is not recognised.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from odwolania2json import ocr  # noqa: E402
from odwolania2json.config import load_settings  # noqa: E402
from odwolania2json.pipeline import Processor  # noqa: E402
from odwolania2json.spell import lexicon  # noqa: E402


def make_scan(source: Path, target: Path) -> None:
    """Save an image-only copy of the first page of a PDF, like a scan."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(source))
    image = document[0].render(scale=150 / 72).to_pil().convert("L")
    document.close()
    image.save(target, format="PDF", resolution=150)


def main() -> int:
    """Load all models, process samples and check the outputs."""
    for model in ("v5", "v6"):
        ocr._rapidocr_engine(model)
    lexicon()
    sample = ROOT / "tests" / "fixtures" / "przyklad_07"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "input" / "case").mkdir(parents=True)
        for pdf in sample.glob("*.pdf"):
            shutil.copy2(pdf, work / "input" / "case" / pdf.name)
        make_scan(sample / "potwierdzenie_przelewu.pdf", work / "input" / "skan_przelewu.pdf")
        settings = load_settings()
        results = Processor(settings, use_llm=False).process_tree(work / "input", work / "output")
        outputs = sorted(p.relative_to(work / "output").as_posix() for p in (work / "output").rglob("*.json"))
        scan = json.loads((work / "output" / "skan_przelewu.json").read_text(encoding="utf-8"))
    print("Outputs:", ", ".join(outputs))
    if len(outputs) != len(results) or "przelew_bankowy" not in scan:
        print("Warm-up check FAILED", file=sys.stderr)
        return 1
    print("Warm-up check OK: OCR models loaded, text PDFs and a scan processed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
