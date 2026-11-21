"""Turn labelled cases into image-only PDFs that look like office scans, for measuring OCR quality.

Every PDF of a case folder is rendered, degraded and saved without a text layer next to a copy of its reference
JSON, so the result can be measured with `python -m odwolania2json eval <out>`.

Levels:
    easy    200 DPI, up to 0.7° skew, light blur
    medium  150 DPI, up to 1.5° skew, blur, sensor noise, JPEG 55
    hard    120 DPI, up to 3° skew, stronger blur, noise, uneven lighting, faded toner, JPEG 30

Usage:
    python tools/simulate_scans.py data_train data_scans/medium --level medium --cases 20 --seed 1
"""

from __future__ import annotations

import argparse
import io
import random
import shutil
from pathlib import Path

LEVELS = {
    "easy": {"dpi": 200, "skew": 0.7, "blur": 0.4, "noise": 0, "jpeg": 85, "light": 0.0, "fade": 0.0},
    "medium": {"dpi": 150, "skew": 1.5, "blur": 0.8, "noise": 8, "jpeg": 55, "light": 0.08, "fade": 0.1},
    "hard": {"dpi": 120, "skew": 3.0, "blur": 1.1, "noise": 14, "jpeg": 30, "light": 0.18, "fade": 0.25},
}


def degrade(image, level: dict, rng: random.Random):
    """Apply skew, blur, faded toner, uneven lighting, noise and JPEG artefacts to a page image."""
    import numpy as np
    from PIL import Image, ImageFilter

    gray = image.convert("L")
    gray = gray.rotate(rng.uniform(-level["skew"], level["skew"]), resample=Image.BICUBIC, expand=True, fillcolor=255)
    if level["blur"]:
        gray = gray.filter(ImageFilter.GaussianBlur(level["blur"]))
    pixels = np.asarray(gray, dtype=np.float32)
    if level["fade"]:
        pixels = 255 - (255 - pixels) * (1 - level["fade"])
    if level["light"]:
        height, width = pixels.shape
        gradient = np.linspace(-level["light"], level["light"], width)[None, :] * rng.choice([-1, 1])
        pixels = pixels * (1 - np.abs(gradient)) + 255 * np.clip(gradient, 0, None)
    if level["noise"]:
        pixels = pixels + np.random.default_rng(rng.randrange(1 << 30)).normal(0, level["noise"], pixels.shape)
    gray = Image.fromarray(np.clip(pixels, 0, 255).astype("uint8"))
    buffer = io.BytesIO()
    gray.save(buffer, format="JPEG", quality=level["jpeg"])
    return Image.open(io.BytesIO(buffer.getvalue()))


def scan_pdf(source: Path, target: Path, level: dict, rng: random.Random) -> None:
    """Render a PDF, degrade each page and save an image-only PDF."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(source))
    pages = [degrade(page.render(scale=level["dpi"] / 72).to_pil(), level, rng) for page in document]
    document.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(target, format="PDF", save_all=True, append_images=pages[1:], resolution=level["dpi"])


def main(argv: list[str] | None = None) -> int:
    """Convert the first N case folders of a labelled dataset into simulated scans."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--level", choices=sorted(LEVELS), default="medium")
    parser.add_argument("--cases", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    rng = random.Random(args.seed)
    cases = sorted(p for p in args.data.iterdir() if p.is_dir() and any(p.glob("*.json")) and any(p.glob("*.pdf")))[: args.cases]
    for case in cases:
        for item in sorted(case.iterdir()):
            target = args.out / case.name / item.name
            if item.suffix.lower() == ".pdf":
                scan_pdf(item, target, LEVELS[args.level], rng)
            elif item.suffix.lower() == ".json":
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        print(f"{case.name}: done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
