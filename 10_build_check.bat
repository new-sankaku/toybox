@echo off
chcp 65001 > /dev/null
echo ========================================
echo   Build Check - All Validations
echo ========================================
echo.

cd /d "%~dp0"

echo [1/6] Backend - Syntax Check...
echo.
cd /d "%~dp0\backend"
call venv\Scripts\activate.bat
python -m py_compile app.py main.py
if %errorlevel% neq 0 (
    echo Error: Backend syntax check failed
    pause
    exit /b 1
)
echo OK
echo.

echo [2/6] Backend - Import Test...
echo.
python -c "from app import create_app; create_app(); print('Import test OK')"
if %errorlevel% neq 0 (
    echo Error: Backend import test failed
    pause
    exit /b 1
)
echo.

echo [3/6] Backend - OpenAPI Spec Generation...
echo.
python scripts/generate_openapi.py
if %errorlevel% neq 0 (
    echo Error: OpenAPI spec generation failed
    pause
    exit /b 1
)
echo.

echo [4/6] Frontend - TypeScript Type Generation...
echo.
cd /d "%~dp0\langgraph-studio"
call npm run generate-types
if %errorlevel% neq 0 (
    echo Error: TypeScript type generation failed
    pause
    exit /b 1
)
echo.

echo [5/6] Frontend - ESLint...
echo.
call npm run lint
if %errorlevel% neq 0 (
    echo Error: ESLint check failed
    pause
    exit /b 1
)
echo.

echo [6/6] Frontend - TypeScript Type Check...
echo.
call npm run typecheck
if %errorlevel% neq 0 (
    echo Error: TypeScript type check failed
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
