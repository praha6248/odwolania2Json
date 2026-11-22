#!/usr/bin/env bash
# One-time setup of the evaluation VM (Ubuntu 24.04, no GPU), run by the team account from the cloned repository:
#   cd /opt/solution && git clone https://github.com/praha6248/odwolania2Json.git repo && bash repo/deploy/azure/setup.sh
# Installs Python 3.13 with uv, creates repo/.venv with requirements.txt, downloads the OCR models in advance,
# runs a check on sample documents and puts RUN.md and run.sh into /opt/solution.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SOLUTION="${SOLUTION:-$(dirname "$REPO")}"
cd "$REPO"

if [ ! -x "$REPO/.tools/bin/uv" ]; then
  python3 -m venv "$REPO/.tools"
  "$REPO/.tools/bin/pip" install --quiet uv
fi
UV="$REPO/.tools/bin/uv"
export UV_PYTHON_INSTALL_DIR="$REPO/.python"

"$UV" python install 3.13
[ -x "$REPO/.venv/bin/python" ] || "$UV" venv --python 3.13 "$REPO/.venv"
"$UV" pip install --python "$REPO/.venv/bin/python" -r requirements.txt

O2J_NO_UPDATE_CHECK=1 "$REPO/.venv/bin/python" "$REPO/deploy/azure/warmup.py"

install -m 755 "$REPO/deploy/azure/run.sh" "$SOLUTION/run.sh"
install -m 644 "$REPO/deploy/azure/RUN.md" "$SOLUTION/RUN.md"
mkdir -p "$SOLUTION/input" "$SOLUTION/output"
chmod -R a+rX "$REPO"
echo "Ready. Evaluation command (from $SOLUTION): sudo bash run.sh"
