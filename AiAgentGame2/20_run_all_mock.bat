@echo off
chcp 65001 > nul
echo ========================================
echo   Backend (Mock) + Frontend 同時起動
echo ========================================
echo.

cd /d "%~dp0"

echo Backend (Mock) を起動中...
start "AiAgentGame2 Backend (Mock)" cmd /k "cd /d "%~dp0\backend" && call venv\Scripts\activate.bat && python main.py --mode mock"

echo.
echo 2秒待機中...
timeout /t 2 /nobreak > nul

echo Frontend を起動中...
start "AiAgentGame2 Frontend" cmd /k "cd /d "%~dp0\langgraph-studio" && npm run dev"

echo.
echo 3秒後にブラウザを開きます...
timeout /t 3 /nobreak > nul

start http://localhost:5173

echo.
echo ========================================
echo   起動完了
echo ========================================
echo.
echo   - Backend: http://localhost:5000
echo   - Frontend: http://localhost:5173
echo.
echo 終了するには各ウィンドウを閉じてください
echo.
