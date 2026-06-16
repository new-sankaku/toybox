@echo off
cd /d %~dp0
if not exist venv (
    python -m venv venv
    venv\Scripts\pip install --upgrade pip "setuptools<70" wheel
    venv\Scripts\pip install -r requirements.txt
)
where ffmpeg >nul 2>nul || echo [警告] ffmpegが見つかりません。録画機能を使うにはffmpegをinstallしてください。他の機能はそのまま使えます。
echo TicTok LIVE Monitor: http://127.0.0.1:8520 を開いてください。
venv\Scripts\python server.py
