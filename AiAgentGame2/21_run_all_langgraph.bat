@echo off
chcp 65001 > nul
echo ========================================
echo   Backend (LangGraph) + Frontend 同時起動
echo ========================================
echo.

cd /d "%~dp0"

if not exist "backend\.env" (
    echo 警告: backend\.env が見つかりません
    echo ANTHROPIC_API_KEY を設定してください
    echo.
    pause
)

echo Backend (LangGraph) を起動中...
start "AiAgentGame2 Backend (LangGraph)" cmd /k "cd /d "%~dp0\backend" && call venv\Scripts\activate.bat && python main.py --mode langgraph"

echo.
echo 2秒待機中...
timeout /t 2 /nobreak > nul

echo Frontend を起動中...
start "AiAgentGame2 Frontend" cmd /k "cd /d "%~dp0\langgraph-studio" && npm run dev"

echo.
echo ========================================
echo   起動完了
echo ========================================
echo.
echo 以下のウィンドウが開きます:
echo   - Backend: http://localhost:8765 (LangGraph Mode)
echo   - Frontend: http://localhost:5173
echo.
echo 終了するには各ウィンドウを閉じてください
echo.
