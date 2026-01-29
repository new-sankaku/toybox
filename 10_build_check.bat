@echo off
chcp 65001 > /dev/null
echo ========================================
echo   Build Check - All Validations
echo ========================================
echo.

cd /d "%~dp0"

echo [1/12] Backend - Ruff Lint...
echo.
cd /d "%~dp0\backend"
call venv\Scripts\activate.bat
ruff check .
if %errorlevel% neq 0 (
    echo Error: Ruff lint failed
    pause
    exit /b 1
)
echo OK
echo.

echo [2/12] Backend - mypy Type Check...
echo.
mypy . --config-file pyproject.toml
if %errorlevel% neq 0 (
    echo Error: mypy type check failed
    pause
    exit /b 1
)
echo OK
echo.

echo [3/12] Backend - Import Test...
echo.
python -c "from app import create_app; create_app(); print('Import test OK')"
if %errorlevel% neq 0 (
    echo Error: Backend import test failed
    pause
    exit /b 1
)
echo.

echo [4/12] Backend - pytest Unit Tests...
echo.
pytest tests/ -v --ignore=tests/contract --ignore=tests/scenarios -x
if %errorlevel% neq 0 (
    echo Error: pytest failed
    pause
    exit /b 1
)
echo.

echo [5/12] Backend - Circular Import Check...
echo.
python scripts/detect_circular_imports.py
if %errorlevel% neq 0 (
    echo Error: Circular imports detected
    pause
    exit /b 1
)
echo.

echo [6/12] Backend - Security Audit (pip-audit)...
echo.
pip-audit --progress-spinner off 2>nul
if %errorlevel% neq 0 (
    echo Warning: Security vulnerabilities found. Review above.
)
echo.

echo [7/12] Backend - OpenAPI Spec Generation...
echo.
python scripts/generate_openapi.py
if %errorlevel% neq 0 (
    echo Error: OpenAPI spec generation failed
    pause
    exit /b 1
)
echo.

echo [8/12] Frontend - TypeScript Type Generation...
echo.
cd /d "%~dp0\langgraph-studio"
call npm run generate-types
if %errorlevel% neq 0 (
    echo Error: TypeScript type generation failed
    pause
    exit /b 1
)
echo.

echo [9/12] Frontend - ESLint...
echo.
call npm run lint
if %errorlevel% neq 0 (
    echo Error: ESLint check failed
    pause
    exit /b 1
)
echo.

echo [10/12] Frontend - TypeScript Type Check...
echo.
call npm run typecheck
if %errorlevel% neq 0 (
    echo Error: TypeScript type check failed
    pause
    exit /b 1
)
echo.

echo [11/12] Frontend - Circular Import Check (madge)...
echo.
call npm run analyze:circular
if %errorlevel% neq 0 (
    echo Error: Circular imports detected in frontend
    pause
    exit /b 1
)
echo.

echo [12/12] Frontend - Unit Tests (Vitest)...
echo.
call npm run test:unit
if %errorlevel% neq 0 (
    echo Error: Unit tests failed
    pause
    exit /b 1
)
echo.

echo ========================================
echo   All checks passed!
echo ========================================
echo.
echo Note: Run "npm run build" for full build check before commit.
echo.
echo Additional analysis tools (run manually):
echo   Backend:  vulture .              (dead code detection)
echo   Frontend: npm run analyze:deadcode  (knip - unused exports)
echo   Frontend: npm run analyze:bundle    (bundle size analysis)
echo.

pause
