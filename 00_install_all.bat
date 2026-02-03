@echo off
chcp 65001 > /dev/null
echo ========================================
echo   AiAgentGame2 - Install
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] Backend...
echo.

cd /d "%~dp0\backend"

python --version
if errorlevel 1 (
    echo Error: Python is not installed
    pause
    exit /b 1
)

if not exist "venv" (
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -r requirements.txt

if errorlevel 1 (
    echo Error: Backend install failed
    pause
    exit /b 1
)

echo.
echo [2/3] Frontend...
echo.

cd /d "%~dp0\langgraph-studio"

node --version
if errorlevel 1 (
    echo Error: Node.js is not installed
    pause
    exit /b 1
)

call npm install

if errorlevel 1 (
    echo Error: Frontend install failed
    pause
    exit /b 1
)

echo.
echo [3/3] Playwright MCP...
echo.

call npm install -D @playwright/mcp
call npx playwright install chromium

if errorlevel 1 (
    echo Error: Playwright install failed
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Install completed
echo ========================================
echo.
echo Run: 99_run_all_testdata.bat
echo.

pause
