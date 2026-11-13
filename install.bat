@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher py was not found. Install Python 3.11 or newer.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -e ".[dev]"
if errorlevel 1 goto :error
if not exist "data" mkdir data
echo.
echo Installation completed.
pause
exit /b 0
:error
echo Installation failed. See the error above.
pause
exit /b 1
