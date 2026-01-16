@echo off
chcp 65001 > nul
echo ========================================
echo   AiAgentGame2 Backend - Mock Mode
echo ========================================
echo.

cd /d "%~dp0"

if not exist "venv" (
    echo エラー: 仮想環境が見つかりません
    echo 先に 00_install.bat を実行してください
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo モックモードで起動します...
echo （実際のLLM呼び出しは行いません）
echo.

python main.py --mode mock

pause
