@echo off
chcp 65001 > nul
echo ========================================
echo   Rebuild - Backend + Frontend
echo ========================================
echo.

cd /d "%~dp0"

echo [1/2] Backend...
echo.

cd /d "%~dp0\backend"

if not exist "venv" (
    echo Error: venv not found. Run 00_install_all.bat first
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo Error: Backend rebuild failed
    pause
    exit /b 1
)

echo.
echo [2/2] Frontend...
echo.

cd /d "%~dp0\langgraph-studio"

if not exist "node_modules" (
    echo Error: node_modules not found. Run 00_install_all.bat first
    pause
    exit /b 1
)

call npm run build

if %errorlevel% neq 0 (
    echo Error: Frontend rebuild failed
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Rebuild completed
echo ========================================
echo.

pause
