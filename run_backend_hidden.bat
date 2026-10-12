@echo off
cd /d %~dp0
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not exist logs mkdir logs
python -u -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info > logs\backend.log 2>&1
