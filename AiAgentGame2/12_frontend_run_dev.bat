@echo off
chcp 65001 > nul
echo ========================================
echo   Frontend - 開発サーバー起動
echo ========================================
echo.

cd /d "%~dp0\langgraph-studio"

call npm run dev

pause
