@echo off
setlocal
cd /d "%~dp0backend"
if exist ".venv\Scripts\python.exe" (
 set "PYTHON=.venv\Scripts\python.exe"
) else (
 set "PYTHON=python"
)
"%PYTHON%" -m compileall -q hayakuchi middleware scripts
if errorlevel 1 exit /b 1
"%PYTHON%" -m pytest -q
if errorlevel 1 exit /b 1
endlocal
