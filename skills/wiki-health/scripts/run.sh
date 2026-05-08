#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -x "$SKILL_DIR/.venv/bin/python" ]; then
  PY="$SKILL_DIR/.venv/bin/python"
else
  PY="python3"
fi

MAIN_PATH="$SKILL_DIR/scripts/health.py"
if [ ! -f "$MAIN_PATH" ]; then
  printf 'Missing target script: %s\n' "$MAIN_PATH" >&2
  exit 1
fi

exec "$PY" "$MAIN_PATH" "$@"
