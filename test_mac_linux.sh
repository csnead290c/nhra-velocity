#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Development environment not found. Run ./run_mac_linux.sh once first."
  exit 1
fi
.venv/bin/python -m pytest -q
