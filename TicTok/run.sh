#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"
if [ ! -d venv ]; then
    python3 -m venv venv
    venv/bin/pip install --upgrade pip "setuptools<70" wheel
    venv/bin/pip install -r requirements.txt
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[警告] ffmpegが見つかりません。録画機能を使うにはffmpegをinstallしてください（例: apt-get install ffmpeg）。他の機能はそのまま使えます。"
fi
echo "TicTok LIVE Monitor: http://127.0.0.1:8520 を開いてください。"
venv/bin/python server.py
