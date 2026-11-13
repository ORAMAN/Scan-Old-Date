@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Locate uv. Install it with the official Astral installer when missing.
where uv >nul 2>nul
if not errorlevel 1 set "UV=uv"

if not defined UV (
  echo uv was not found. Installing uv from the official Astral installer...
  where powershell >nul 2>nul
  if errorlevel 1 (
    echo PowerShell was not found. Install uv manually: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  if errorlevel 1 goto :uv_error

  if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
  if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UV=%USERPROFILE%\.cargo\bin\uv.exe"
  if not defined UV (
    where uv >nul 2>nul
    if not errorlevel 1 set "UV=uv"
  )
)

if not defined UV goto :uv_error

echo.
"%UV%" --version
if errorlevel 1 goto :uv_error

echo.
echo Installing managed CPython 3.12 x64...
"%UV%" python install 3.12
if errorlevel 1 goto :error

echo.
echo Creating a clean virtual environment with standard CPython 3.12...
"%UV%" venv --clear --python 3.12 .venv
if errorlevel 1 goto :error

echo.
echo Resolving and installing project dependencies with binary packages only...
"%UV%" sync --extra dev --no-build-package Pillow --no-build-package opencv-python --no-build-package PySide6 --no-build-package shiboken6 --no-build-package numpy
if errorlevel 1 goto :error

echo.
echo Verifying the runtime and key dependencies...
".venv\Scripts\python.exe" -c "import sys, platform, PySide6, cv2, PIL; print('Python:', sys.version); print('Architecture:', platform.architecture()[0]); print('PySide6:', PySide6.__version__); print('OpenCV:', cv2.__version__); print('Pillow:', PIL.__version__)"
if errorlevel 1 goto :error

if not exist "data" mkdir data
echo.
echo Installation completed successfully.
pause
exit /b 0

:uv_error
echo.
echo Could not install or locate uv.
echo Install it manually from https://docs.astral.sh/uv/getting-started/installation/
pause
exit /b 1

:error
echo.
echo Installation failed. No success status is reported.
echo Review the error above. uv uses standard CPython 3.12 and binary wheels only.
pause
exit /b 1
