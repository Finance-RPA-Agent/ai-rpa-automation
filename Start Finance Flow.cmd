@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup Finance Flow.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" start_product.py
if errorlevel 1 pause
