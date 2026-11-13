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
if exist ".venv\Scripts\python.exe" (
  call ".venv\Scripts\activate.bat"
  python -m pip install -e .
)
echo Update completed.
pause
exit /b 0
:error
echo Update failed. Review the messages above.
pause
exit /b 1
