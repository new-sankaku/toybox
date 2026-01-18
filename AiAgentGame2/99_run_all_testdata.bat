@echo off
chcp 65001 > nul
echo ========================================
echo   Backend (TestData) + Frontend
echo ========================================
echo.

cd /d "%~dp0"

echo Starting Backend (TestData)...
start "AiAgentGame2 Backend" cmd /k "cd /d "%~dp0\backend" && call venv\Scripts\activate.bat && python main.py --mode testdata"

echo.
timeout /t 2 /nobreak > nul

echo Starting Frontend...
start "AiAgentGame2 Frontend" cmd /k "cd /d "%~dp0\langgraph-studio" && npm run dev"

echo.
timeout /t 3 /nobreak > nul

start http://localhost:5173

echo.
echo ========================================
echo   Started
echo ========================================
echo.
echo   - Backend: http://localhost:5000
echo   - Frontend: http://localhost:5173
echo.
echo Close windows to stop
echo.
