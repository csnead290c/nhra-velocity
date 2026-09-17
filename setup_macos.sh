#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-desktop.txt
printf '\nNHRA Velocity macOS development environment is ready.\nRun: ./.venv/bin/python desktop.py\n'
