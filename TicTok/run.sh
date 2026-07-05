#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"
if [ ! -d venv ]; then
    python3 -m venv venv || { echo "[ERROR] Failed to create virtual environment. Is python3 installed?"; exit 1; }
    if ! (venv/bin/pip install --upgrade pip "setuptools<70" wheel \
        && venv/bin/pip install -r requirements.txt \
        && venv/bin/python -m playwright install chromium); then
        echo "[ERROR] Setup failed during dependency installation. Removing incomplete venv so the next run retries cleanly."
        rm -rf venv
        exit 1
    fi
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[警告] ffmpegが見つかりません。録画機能を使うにはffmpegをinstallしてください（例: apt-get install ffmpeg）。他の機能はそのまま使えます。"
fi
# Kill a leftover TicTok server from a previous run (a main.py process whose
# working dir is exactly this folder) so it cannot keep holding the port. Only
# this app's own orphan is targeted; unrelated processes are never touched.
APP_DIR="$(pwd)"
for pid in $(pgrep -f 'main\.py' 2>/dev/null || true); do
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    if [ "$cwd" = "$APP_DIR" ]; then
        echo "[INFO] Stopping leftover TicTok server PID $pid"
        kill "$pid" 2>/dev/null || true
    fi
done
echo "TicTok LIVE Monitor: http://127.0.0.1:8520 を開いてください。"
venv/bin/python main.py
