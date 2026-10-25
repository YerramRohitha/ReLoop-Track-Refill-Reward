@echo off
REM Windows: creates a virtual environment, installs Flask and starts ReLoop
cd /d %~dp0
if not exist .venv (python -m venv .venv)
call .venv\Scripts\activate
pip install -r requirements.txt
python backend\app.py
