@echo off
chcp 65001 > /dev/null

REM ANSI color codes
for /F %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
set "RED=%ESC%[31m"
set "GREEN=%ESC%[32m"
set "YELLOW=%ESC%[33m"
set "RESET=%ESC%[0m"

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
    echo %RED%Error: Ruff lint failed%RESET%
    pause
    exit /b 1
)
echo %GREEN%OK%RESET%
echo.

echo [2/12] Backend - mypy Type Check...
echo.
mypy . --config-file pyproject.toml
if %errorlevel% neq 0 (
    echo %YELLOW%Retrying with cache clear...%RESET%
    if exist ".mypy_cache" rmdir /s /q .mypy_cache
    mypy . --config-file pyproject.toml
    if %errorlevel% neq 0 (
        echo %RED%Error: mypy type check failed%RESET%
        pause
        exit /b 1
    )
)
echo %GREEN%OK%RESET%
echo.

echo [3/12] Backend - Import Test...
echo.
python -c "from app import create_app; create_app(); print('Import test OK')"
if %errorlevel% neq 0 (
    echo %RED%Error: Backend import test failed%RESET%
    pause
    exit /b 1
)
echo.

echo [4/12] Backend - pytest Unit Tests...
echo.
pytest tests/ -q --no-header --tb=short --ignore=tests/contract --ignore=tests/scenarios -x
if %errorlevel% neq 0 (
    echo %RED%Error: pytest failed%RESET%
    pause
    exit /b 1
)
echo.

echo [5/12] Backend - Circular Import Check...
echo.
python scripts/detect_circular_imports.py
if %errorlevel% neq 0 (
    echo %RED%Error: Circular imports detected%RESET%
    pause
    exit /b 1
)
echo.

echo [6/12] Backend - Security Audit (pip-audit)...
echo.
pip-audit --progress-spinner off 2>nul
if %errorlevel% neq 0 (
    echo %YELLOW%Warning: Security vulnerabilities found. Review above.%RESET%
)
echo.

echo [7/12] Backend - OpenAPI Spec Generation...
echo.
python scripts/generate_openapi.py
if %errorlevel% neq 0 (
    echo %RED%Error: OpenAPI spec generation failed%RESET%
    pause
    exit /b 1
)
echo.

echo [8/12] Frontend - TypeScript Type Generation...
echo.
cd /d "%~dp0\langgraph-studio"
call npm run generate-types
if %errorlevel% neq 0 (
    echo %RED%Error: TypeScript type generation failed%RESET%
    pause
    exit /b 1
)
echo.

echo [9/12] Frontend - ESLint...
echo.
call npm run lint
if %errorlevel% neq 0 (
    echo %RED%Error: ESLint check failed%RESET%
    pause
    exit /b 1
)
echo.

echo [10/12] Frontend - TypeScript Type Check...
echo.
call npm run typecheck
if %errorlevel% neq 0 (
    echo %RED%Error: TypeScript type check failed%RESET%
    pause
    exit /b 1
)
echo.

echo [11/12] Frontend - Circular Import Check (madge)...
echo.
call npm run analyze:circular
if %errorlevel% neq 0 (
    echo %RED%Error: Circular imports detected in frontend%RESET%
    pause
    exit /b 1
)
echo.

echo [12/12] Frontend - Unit Tests (Vitest)...
echo.
call npm run test:unit
if %errorlevel% neq 0 (
    echo %RED%Error: Unit tests failed%RESET%
    pause
    exit /b 1
)
echo.

echo ========================================
echo   %GREEN%All checks passed!%RESET%
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
