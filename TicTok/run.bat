@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist venv (
    python -m venv venv || goto :venv_failed
    venv\Scripts\pip install --upgrade pip "setuptools<70" wheel || goto :setup_failed
    venv\Scripts\pip install -r requirements.txt || goto :setup_failed
    venv\Scripts\python -m playwright install chromium || goto :setup_failed
)
where ffmpeg >nul 2>nul || echo [WARN] ffmpeg not found. Recording needs ffmpeg; other features work without it.
rem Kill a leftover TicTok server from a previous run (matched strictly by this
rem folder's venv python path) so it cannot keep holding the port. Only this
rem app's own orphan is targeted; unrelated processes are never touched.
powershell -NoProfile -Command "$p=(Resolve-Path '%~dp0venv\Scripts\python.exe' -EA SilentlyContinue).Path; if($p){Get-CimInstance Win32_Process | ?{$_.ExecutablePath -ieq $p} | %%{Write-Host ('[INFO] Stopping leftover TicTok server PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue}}"
echo Open TicTok LIVE Monitor in your browser: http://127.0.0.1:8520
venv\Scripts\python main.py || goto :server_failed
goto :eof

:venv_failed
echo [ERROR] Failed to create virtual environment. Is Python installed and on PATH?
goto :abort

:setup_failed
echo [ERROR] Setup failed during dependency installation. Removing incomplete venv so the next run retries cleanly.
rmdir /s /q venv 2>nul
goto :abort

:server_failed
echo [ERROR] Server exited with an error. See the messages above for details.
goto :abort

:abort
echo.
pause
exit /b 1
