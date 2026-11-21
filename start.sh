#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3.13}"
command -v "$PY" >/dev/null 2>&1 || PY=python3
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
fi
if [ "$#" -eq 0 ]; then
  exec .venv/bin/python -m odwolania2json run
fi
exec .venv/bin/python -m odwolania2json "$@"
