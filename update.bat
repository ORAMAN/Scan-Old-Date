@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
  echo Git was not found. Install Git for Windows.
  pause
  exit /b 1
)

echo Checking repository status...
git status --short
if errorlevel 1 goto :error

for /f %%i in ('git status --porcelain') do set LOCAL_CHANGES=1
if defined LOCAL_CHANGES (
  echo.
  echo Local changes detected. Choose:
  echo   1 - Stash local changes, update, then restore them
  echo   2 - Discard local changes and update
  echo   3 - Exit without updating
  choice /c 123 /n /m "Your choice: "
  if errorlevel 3 exit /b 0
  if errorlevel 2 (
    echo WARNING: local modifications will be discarded.
    choice /c YN /n /m "Confirm discard? [Y/N] "
    if errorlevel 2 exit /b 0
    git reset --hard
    if errorlevel 1 goto :error
    git clean -fd
    if errorlevel 1 goto :error
  ) else (
    git stash push -u -m "Scan-Old-Date update safety stash"
    if errorlevel 1 goto :error
    set RESTORE_STASH=1
  )
)

git pull --ff-only
if errorlevel 1 goto :error

if defined RESTORE_STASH (
  git stash pop
  if errorlevel 1 (
    echo Stash restore had conflicts. Your changes remain in the stash if not fully applied.
    pause
    exit /b 1
  )
)

where uv >nul 2>nul
if errorlevel 1 (
  if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
  ) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "UV=%USERPROFILE%\.cargo\bin\uv.exe"
  ) else (
    echo uv was not found. Run install.bat to install uv and initialize the environment.
    pause
    exit /b 1
  )
) else (
  set "UV=uv"
)

set "RECREATE_VENV="
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys,sysconfig; assert sys.version_info[:2] == (3,12) and not sysconfig.get_config_var('Py_GIL_DISABLED')"
  if errorlevel 1 set "RECREATE_VENV=1"
) else (
  set "RECREATE_VENV=1"
)

if defined RECREATE_VENV (
  echo Creating a standard CPython 3.12 environment managed by uv...
  "%UV%" python install 3.12
  if errorlevel 1 goto :error
  "%UV%" venv --clear --python 3.12 .venv
  if errorlevel 1 goto :error
)

echo.
echo Synchronizing project dependencies with uv...
"%UV%" sync --extra dev --no-build-package Pillow --no-build-package opencv-python --no-build-package PySide6 --no-build-package shiboken6 --no-build-package numpy
if errorlevel 1 goto :error

".venv\Scripts\python.exe" -c "import sys, PySide6, cv2, PIL; print('Runtime OK:', sys.version.split()[0], '| PySide6:', PySide6.__version__, '| OpenCV:', cv2.__version__, '| Pillow:', PIL.__version__)"
if errorlevel 1 goto :error

echo.
echo Update completed successfully.
pause
exit /b 0

:error
echo.
echo Update failed. Review the messages above. The script will not report success after a failed step.
pause
exit /b 1
