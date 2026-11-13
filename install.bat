@echo off
setlocal
cd /d "%~dp0"

REM PySide6 and OpenCV require a supported 64-bit CPython build.
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher was not found.
  echo Install Python 3.12 x64 from https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3.12-64 -m venv .venv
  if errorlevel 1 (
    echo Could not create a Python 3.12 x64 environment.
    echo Install Python 3.12 x64, enable the Python Launcher, then run this file again.
    pause
    exit /b 1
  )
)

set "PYTHON=.venv\Scripts\python.exe"
"%PYTHON%" -c "import platform,sys; print('Detected interpreter:', sys.version.split()[0], platform.architecture()[0])"

"%PYTHON%" -c "import sys,struct; assert sys.version_info >= (3,11) and sys.version_info < (3,14) and struct.calcsize('P') == 8" >nul 2>nul
if errorlevel 1 (
  echo The existing .venv is not a supported 64-bit Python 3.11-3.13 environment.
  echo Delete the .venv folder and install Python 3.12 x64, then rerun install.bat.
  pause
  exit /b 1
)

"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :error

REM Require binary wheels for native packages: do not attempt local C++ builds.
"%PYTHON%" -m pip install --only-binary=Pillow,opencv-python,PySide6 -e ".[dev]"
if errorlevel 1 goto :error

if not exist "data" mkdir data
echo.
echo Installation completed successfully.
pause
exit /b 0

:error
echo.
echo Installation failed. Check the interpreter above and the package index configuration.
echo For PySide6/OpenCV, use official 64-bit CPython 3.12 and the public PyPI index.
pause
exit /b 1
