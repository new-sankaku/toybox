@echo off
chcp 65001 > nul
echo ========================================
echo   Frontend - プロダクションビルド
echo ========================================
echo.

cd /d "%~dp0\langgraph-studio"

call npm run build

pause
