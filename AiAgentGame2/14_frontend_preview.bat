@echo off
chcp 65001 > nul
echo ========================================
echo   Frontend - ビルド後プレビュー
echo ========================================
echo.

cd /d "%~dp0\langgraph-studio"

call npm run preview

pause
