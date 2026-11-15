@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup Finance Flow.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run_tests.py %*
set "test_exit_code=%errorlevel%"
pause
exit /b %test_exit_code%
