@echo off
chcp 65001 >nul
echo ========================================
echo   Screenshot - All Pages
echo ========================================
echo.

cd /d "%~dp0"

echo Capturing screenshots...
echo.
cd langgraph-studio
call node scripts/screenshot.cjs
if %errorlevel% neq 0 (
    echo.
    echo Error: Screenshot capture failed.
    echo Make sure the frontend is running (npm run dev)
    pause
    exit /b 1
)
echo.
echo ========================================
echo   Done! Screenshots saved to screenshots/
echo ========================================
pause
