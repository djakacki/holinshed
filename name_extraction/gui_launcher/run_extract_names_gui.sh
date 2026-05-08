#!/bin/sh
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$SCRIPT_DIR/extract_names_gui.py"
fi

if command -v python >/dev/null 2>&1; then
  exec python "$SCRIPT_DIR/extract_names_gui.py"
fi

echo "Python was not found."
