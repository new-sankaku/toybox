#!/bin/bash
set -e
echo "========================================"
echo "  Build Check - All Validations"
echo "========================================"
echo ""

cd "$(dirname "$0")"
ROOT_DIR=$(pwd)

echo "[1/12] Backend - Ruff Lint..."
cd "$ROOT_DIR/backend"
if [ -d "venv" ]; then
    source venv/bin/activate 2>/dev/null || true
fi
ruff check .
echo "OK"
echo ""

echo "[2/12] Backend - mypy Type Check..."
mypy . --config-file pyproject.toml
echo "OK"
echo ""

echo "[3/12] Backend - Import Test..."
python -c "from app import create_app; create_app(); print('Import test OK')"
echo ""

echo "[4/12] Backend - pytest Unit Tests..."
pytest tests/ -v --ignore=tests/contract --ignore=tests/scenarios -x
echo ""

echo "[5/12] Backend - Circular Import Check..."
python scripts/detect_circular_imports.py
echo ""

echo "[6/12] Backend - Security Audit (pip-audit)..."
pip-audit --progress-spinner off 2>/dev/null || echo "Warning: Security vulnerabilities found or pip-audit unavailable"
echo ""

echo "[7/12] Backend - OpenAPI Spec Generation..."
python scripts/generate_openapi.py
echo ""

echo "[8/12] Frontend - TypeScript Type Generation..."
cd "$ROOT_DIR/langgraph-studio"
npm run generate-types
echo ""

echo "[9/12] Frontend - ESLint..."
npm run lint
echo ""

echo "[10/12] Frontend - TypeScript Type Check..."
npm run typecheck
echo ""

echo "[11/12] Frontend - Circular Import Check (madge)..."
npm run analyze:circular
echo ""

echo "[12/12] Frontend - Unit Tests (Vitest)..."
npm run test:unit
echo ""

echo "========================================"
echo "  All checks passed!"
echo "========================================"
echo ""
echo "Note: Run \"npm run build\" for full build check before commit."
echo ""
echo "Additional analysis tools (run manually):"
echo "  Backend:  vulture .              (dead code detection)"
echo "  Frontend: npm run analyze:deadcode  (knip - unused exports)"
echo "  Frontend: npm run analyze:bundle    (bundle size analysis)"
