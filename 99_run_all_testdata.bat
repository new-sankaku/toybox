@echo off
chcp 65001 > /dev/null
setlocal

set SCRIPT_DIR=%~dp0

echo Resetting test database...
if exist "%SCRIPT_DIR%backend\data\testdata.db" (
    del /f /q "%SCRIPT_DIR%backend\data\testdata.db*" 2> /dev/null
)
echo OK

echo Running seed script...
cd /d "%SCRIPT_DIR%backend"
call venv\Scripts\activate.bat
python seeds/testdata_seed.py --reset
cd /d "%SCRIPT_DIR%"

echo.
powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_testdata.ps1"
