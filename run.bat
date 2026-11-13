@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m scan_old_date.gui
if errorlevel 1 (
  echo Application exited with an error.
  pause
)
