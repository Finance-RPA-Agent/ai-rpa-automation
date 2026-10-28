@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto :failed
)
if exist "product\requirements-lock.txt" (
  ".venv\Scripts\python.exe" -m pip install -r product\requirements-lock.txt
) else (
  ".venv\Scripts\python.exe" -m pip install -r product\requirements.txt
)
if errorlevel 1 goto :failed
echo.
echo Python setup is complete.
echo Install Ollama if needed, then run: ollama pull qwen3.5:4b
echo Start the product using Start Finance Flow.cmd.
pause
exit /b 0
:failed
echo Setup failed. Check the errors above and product\README.md.
pause
exit /b 1
