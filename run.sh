#!/bin/sh
# Mac / Linux: creates a virtual environment, installs Flask and starts ReLoop
cd "$(dirname "$0")"
python3 -m venv .venv 2>/dev/null
. .venv/bin/activate
pip install -r requirements.txt
python backend/app.py
