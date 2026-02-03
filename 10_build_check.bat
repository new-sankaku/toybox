@echo off
chcp 65001 >nul
echo ========================================
echo   Build Check - All Validations
echo ========================================
echo.

cd /d "%~dp0"

echo [1/17] Check for 'nul' files...
echo.
cd /d "%~dp0backend"
call venv\Scripts\activate.bat
python scripts/build_checks.py nul
if %errorlevel% neq 0 (
    echo.
    echo Error: Delete 'nul' files and retry.
    pause
    exit /b 1
)
echo OK
echo.

echo [2/17] Backend - Syntax Check (all .py files)...
echo.
python scripts/build_checks.py syntax
if %errorlevel% neq 0 (
    echo.
    echo Error: Backend syntax check failed
    pause
    exit /b 1
)
echo OK
echo.

echo [3/17] Backend - print() usage check...
echo.
python scripts/build_checks.py print
if errorlevel 1 goto print_error
echo OK
echo.
goto print_done
:print_error
echo.
echo Error: Use get_logger instead of print
pause
exit /b 1
:print_done

echo [4/17] Backend - Ruff linter...
echo.
python -m ruff check . --exclude venv,__pycache__,tests,seeds,scripts --select E9,F63,F7,F82
if %errorlevel% neq 0 (
    echo Error: Ruff check failed - critical errors found
    pause
    exit /b 1
)
echo OK
echo.

echo [5/17] Backend - OpenAPI Spec Generation...
echo.
python scripts/generate_openapi.py
if %errorlevel% neq 0 (
    echo Error: OpenAPI spec generation failed
    pause
    exit /b 1
)
echo.

echo [6/17] Frontend - TypeScript Type Generation...
echo.
cd /d "%~dp0\langgraph-studio"
call npm run generate-types
if %errorlevel% neq 0 (
    echo Error: TypeScript type generation failed
    pause
    exit /b 1
)
echo.

echo [7/17] API Type Consistency Check...
echo.
set "OPENAPI_JSON=%~dp0langgraph-studio\src\types\openapi.json"
set "API_GENERATED=%~dp0langgraph-studio\src\types\api-generated.ts"
for %%A in ("%OPENAPI_JSON%") do set "OPENAPI_TIME=%%~tA"
for %%A in ("%API_GENERATED%") do set "GENERATED_TIME=%%~tA"
if "%OPENAPI_TIME%" gtr "%GENERATED_TIME%" (
    echo Error: openapi.json is newer than api-generated.ts
    echo Run: npm run generate-types
    pause
    exit /b 1
)
echo OK
echo.

echo [8/17] Frontend - ESLint...
echo.
call npm run lint
if %errorlevel% neq 0 (
    echo Error: ESLint check failed
    pause
    exit /b 1
)
echo.

echo [9/17] Frontend - TypeScript Type Check...
echo.
call npm run typecheck
if %errorlevel% neq 0 (
    echo Error: TypeScript type check failed
    pause
    exit /b 1
)
echo.

echo [10/17] Frontend - Surface class usage...
echo.
node scripts/build_checks.cjs surface
if %errorlevel% neq 0 (
    echo Error: Use nier-surface-* instead of bg/text combination
    pause
    exit /b 1
)
echo OK
echo.

echo [11/17] Frontend - Color emoji check...
echo.
node scripts/build_checks.cjs emoji
if %errorlevel% neq 0 (
    echo Error: Use Lucide icons instead of color emojis
    pause
    exit /b 1
)
echo OK
echo.

echo [12/17] Frontend - Inline style check...
echo.
node scripts/build_checks.cjs inline-style
if %errorlevel% neq 0 (
    echo Error: Use Tailwind classes instead of inline styles
    pause
    exit /b 1
)
echo OK
echo.

echo [13/17] Backend - Schema registration chain...
echo.
cd /d "%~dp0backend"
python scripts/build_checks.py schema
if %errorlevel% neq 0 (
    echo Error: Schema registration incomplete
    echo Check: schemas/__init__.py -^> generator.py import -^> schemas_list
    pause
    exit /b 1
)
echo OK
echo.

echo [14/17] Frontend - WebSocket handler check...
echo.
cd /d "%~dp0\langgraph-studio"
node scripts/build_checks.cjs websocket
if %errorlevel% neq 0 (
    echo Error: WebSocket event handlers incomplete
    echo Check: ServerToClientEvents vs socket.on handlers
    pause
    exit /b 1
)
echo OK
echo.

echo [15/17] Backend/Frontend - WebSocket events consistency...
echo.
cd /d "%~dp0backend"
python scripts/build_checks.py websocket-events
if %errorlevel% neq 0 (
    echo Error: WebSocket events mismatch between Backend and Frontend
    echo Check: Backend emit calls vs Frontend ServerToClientEvents
    pause
    exit /b 1
)
echo OK
echo.

echo [16/17] Backend - Schema API usage check...
echo.
python scripts/build_checks.py schema-usage
if %errorlevel% neq 0 (
    echo Warning: Some schemas not used in API paths
)
echo OK
echo.

echo [17/17] Backend - Data flow type check (Pydantic ↔ TypeScript)...
echo.
python scripts/analyze_dataflow.py --ci
if %errorlevel% neq 0 (
    echo.
    echo Error: Field mismatch between Pydantic schemas and TypeScript interfaces
    echo Fix: Sync backend/schemas/ with langgraph-studio/src/types/
    pause
    exit /b 1
)
echo OK
echo.

echo ========================================
echo   All 17 checks passed!
echo ========================================
echo.
echo Note: Run "npm run build" for full build check before commit.
echo.

pause
