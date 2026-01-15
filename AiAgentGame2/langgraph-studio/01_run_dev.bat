@echo off
chcp 65001 > nul
echo ========================================
echo   LangGraph Studio - 開発サーバー起動
echo ========================================
echo.

cd /d "%~dp0"

call npm run dev

pause
