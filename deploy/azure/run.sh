#!/usr/bin/env bash
# Evaluation entry point: converts every PDF in input/ (also in subfolders) into a JSON file with the same name in
# output/, mirroring the folder tree. Documents outside the configured types get {}. No interaction, no network.
set -euo pipefail

SOLUTION="$(cd "$(dirname "$0")" && pwd)"
REPO="$SOLUTION/repo"
export O2J_NO_UPDATE_CHECK=1
export O2J_CACHE_DIR="$REPO/.ocr-cache"

mkdir -p "$SOLUTION/output"
cd "$REPO"
"$REPO/.venv/bin/python" -m odwolania2json run -i "$SOLUTION/input" -o "$SOLUTION/output" --workers 0 --time-limit 40
