@echo off
REM Builds BALE_DOWNLOAD_HUB.exe with PyInstaller. Usage: build.bat [onefile]
setlocal enableextensions
cd /d "%~dp0"
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.11 or newer was not found. Install Python 3.12 from https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv || ( echo Could not create the virtual environment. & pause & exit /b 1 )
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-dev.txt || ( echo Install failed. & pause & exit /b 1 )
".venv\Scripts\python.exe" scripts\build.py %*
if errorlevel 1 ( echo BUILD FAILED & pause & exit /b 1 )
echo.
echo Build finished. See the dist folder.
endlocal
