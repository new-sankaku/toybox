#!/bin/sh
set -e
cd "$(dirname "$0")/backend"
if [ -x .venv/bin/python ]; then
 PYTHON=.venv/bin/python
else
 PYTHON=python3
fi
"$PYTHON" -m compileall -q hayakuchi middleware scripts
"$PYTHON" -m pytest -q
