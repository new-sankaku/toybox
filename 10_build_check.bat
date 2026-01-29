@echo off
chcp 65001 > /dev/null
echo ========================================
echo   Build Check - All Validations
echo ========================================
echo.

cd /d "%~dp0"

echo [1/8] Backend - Ruff Lint...
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

echo [2/8] Backend - mypy Type Check...
echo.
mypy . --config-file pyproject.toml
if %errorlevel% neq 0 (
    echo Error: mypy type check failed
    pause
    exit /b 1
)
echo OK
echo.

echo [3/8] Backend - Import Test...
echo.
python -c "from app import create_app; create_app(); print('Import test OK')"
if %errorlevel% neq 0 (
    echo Error: Backend import test failed
    pause
    exit /b 1
)
echo.

echo [4/8] Backend - OpenAPI Spec Generation...
echo.
python scripts/generate_openapi.py
if %errorlevel% neq 0 (
    echo Error: OpenAPI spec generation failed
    pause
    exit /b 1
)
echo.

echo [5/8] Frontend - TypeScript Type Generation...
echo.
cd /d "%~dp0\langgraph-studio"
call npm run generate-types
if %errorlevel% neq 0 (
    echo Error: TypeScript type generation failed
    pause
    exit /b 1
)
echo.

echo [6/8] Frontend - ESLint...
echo.
call npm run lint
if %errorlevel% neq 0 (
    echo Error: ESLint check failed
    pause
    exit /b 1
)
echo.

echo [7/8] Frontend - TypeScript Type Check...
echo.
call npm run typecheck
if %errorlevel% neq 0 (
    echo Error: TypeScript type check failed
    pause
    exit /b 1
)
echo.

echo [8/8] Frontend - Unit Tests (Vitest)...
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

pause
