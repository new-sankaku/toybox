#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8080}"
PY="$(command -v python3 || command -v python)"
echo "POSTER FORGE  http://localhost:${PORT}/"
exec "$PY" -m http.server "$PORT" --directory "$DIR"
