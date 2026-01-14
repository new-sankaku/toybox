@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
echo ========================================
echo AI Agent Game Creator - Dashboard
echo ========================================
echo.

REM Check Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python が見つかりません
    pause
    exit /b 1
)

REM Create output directory
if not exist "output" mkdir output
if not exist "output\games" mkdir output\games
if not exist "output\logs" mkdir output\logs
if not exist "output\assets" mkdir output\assets
if not exist "output\feedback" mkdir output\feedback
if not exist "output\status" mkdir output\status

echo [INFO] 出力ディレクトリ: output/
echo [INFO] サーバー起動中...
echo [INFO] ブラウザで http://localhost:8080 を開いてください
echo [INFO] 終了するには Ctrl+C を押してください
echo.

python -m src.dashboard.server

pause
