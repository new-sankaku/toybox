@echo off
chcp 65001 > nul
echo ========================================
echo   AiAgentGame2 Backend - LangGraph Mode
echo ========================================
echo.

cd /d "%~dp0"

if not exist "venv" (
    echo エラー: 仮想環境が見つかりません
    echo 先に 00_install.bat を実行してください
    pause
    exit /b 1
)

if not exist ".env" (
    echo 警告: .env ファイルが見つかりません
    echo ANTHROPIC_API_KEY が設定されていることを確認してください
    echo.
)

call venv\Scripts\activate.bat

echo LangGraphモードで起動します...
echo （Claude APIを使用して実際のコンテンツを生成）
echo.

python main.py --mode langgraph

pause
