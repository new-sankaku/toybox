#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"
if [ ! -d venv ]; then
    python3 -m venv venv
    venv/bin/pip install --upgrade pip "setuptools<70" wheel
    venv/bin/pip install -r requirements.txt
fi
venv/bin/python server.py
