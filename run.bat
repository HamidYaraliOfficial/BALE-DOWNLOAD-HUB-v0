@echo off
REM BALE DOWNLOAD HUB - run from source. Creates a virtual environment on first run.
setlocal enableextensions
cd /d "%~dp0"

REM --- find a Python 3.11+ (tries the Windows launcher with explicit versions first)
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>nul && set "PY=python"

if not defined PY goto :nopython
echo Using:
%PY% --version

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv || goto :venvfail
)
set "STAMP=.venv\.deps_installed"
fc /b requirements.txt "%STAMP%" >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies - this can take a few minutes the first time...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :pipfail
  copy /y requirements.txt "%STAMP%" >nul
)
if /i "%~1"=="console" (
  ".venv\Scripts\python.exe" -m app.main
) else (
  start "" ".venv\Scripts\pythonw.exe" -m app.main
)
endlocal
exit /b 0

:nopython
echo.
echo Python 3.11 or newer was NOT found on this computer.
echo.
echo Python versions the Windows launcher knows about:
where py >nul 2>nul && py -0p
echo.
echo What the "python" command reports:
python --version 2>nul
echo.
echo FIX: install Python 3.12 from https://www.python.org/downloads/windows/
echo      and tick "Add python.exe to PATH" on the first installer screen. Then run this file again.
echo.
echo If typing "python" opens the Microsoft Store instead, switch that off:
echo   Settings, Apps, Advanced app settings, App execution aliases, turn off the two "python" entries.
echo.
pause
exit /b 1

:venvfail
echo Could not create the virtual environment. If .venv exists from an older Python, delete the .venv folder and retry.
pause
exit /b 1

:pipfail
echo Dependency installation failed. Check your internet connection (or proxy) and run this file again.
pause
exit /b 1
