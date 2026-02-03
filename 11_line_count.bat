@echo off
chcp 65001 >nul
echo.

cd /d "%~dp0backend"
call venv\Scripts\activate.bat
python scripts/line_count.py

pause
