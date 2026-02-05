@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set TOTAL=20
set TEMPFILE=%TEMP%\build_check_output.txt

echo Build Check - %TOTAL% checks
echo ========================================

cd /d "%~dp0backend"
call venv\Scripts\activate.bat >nul 2>&1

<nul set /p="[1/%TOTAL%] nul files... "
python scripts/build_checks.py nul >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[2/%TOTAL%] Backend syntax... "
python scripts/build_checks.py syntax >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[3/%TOTAL%] Backend imports... "
python scripts/build_checks.py imports >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[4/%TOTAL%] Backend print()... "
python scripts/build_checks.py print >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[5/%TOTAL%] Backend Ruff... "
python -m ruff check . --exclude venv,__pycache__,tests,seeds,scripts --select E9,F63,F7,F82 >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[6/%TOTAL%] OpenAPI generation... "
python scripts/generate_openapi.py >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

cd /d "%~dp0langgraph-studio"

<nul set /p="[7/%TOTAL%] TypeScript types... "
call npm run generate-types >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[8/%TOTAL%] API type consistency... "
set "OPENAPI_JSON=%~dp0langgraph-studio\src\types\openapi.json"
set "API_GENERATED=%~dp0langgraph-studio\src\types\api-generated.ts"
for %%A in ("%OPENAPI_JSON%") do set "OPENAPI_TIME=%%~tA"
for %%A in ("%API_GENERATED%") do set "GENERATED_TIME=%%~tA"
if "%OPENAPI_TIME%" gtr "%GENERATED_TIME%" (
    echo NG
    echo openapi.json is newer than api-generated.ts
    goto :fail
)
echo OK

<nul set /p="[9/%TOTAL%] Frontend ESLint... "
call npm run lint >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[10/%TOTAL%] Frontend TypeScript... "
call npm run typecheck >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[11/%TOTAL%] Surface class... "
node scripts/build_checks.cjs surface >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[12/%TOTAL%] Color emoji... "
node scripts/build_checks.cjs emoji >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[13/%TOTAL%] Inline style... "
node scripts/build_checks.cjs inline-style >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

cd /d "%~dp0backend"

<nul set /p="[14/%TOTAL%] Schema registration... "
python scripts/build_checks.py schema >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

cd /d "%~dp0langgraph-studio"

<nul set /p="[15/%TOTAL%] WebSocket handler... "
node scripts/build_checks.cjs websocket >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

cd /d "%~dp0backend"

<nul set /p="[16/%TOTAL%] WebSocket events... "
python scripts/build_checks.py websocket-events >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[17/%TOTAL%] Schema API usage... "
python scripts/build_checks.py schema-usage >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG ^(warning^)
) else (
    echo OK
)

<nul set /p="[18/%TOTAL%] Data flow types... "
python scripts/analyze_dataflow.py --ci >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

cd /d "%~dp0langgraph-studio"

<nul set /p="[19/%TOTAL%] Sidebar init... "
node scripts/build_checks.cjs sidebar-init >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

<nul set /p="[20/%TOTAL%] State sync... "
node scripts/build_checks.cjs state-sync >"%TEMPFILE%" 2>&1
if !errorlevel! neq 0 (
    echo NG
    type "%TEMPFILE%"
    goto :fail
)
echo OK

echo ========================================
echo All %TOTAL% checks passed!
echo ========================================
del "%TEMPFILE%" 2>nul
pause
exit /b 0

:fail
echo.
echo ========================================
echo Build check failed
echo ========================================
del "%TEMPFILE%" 2>nul
pause
exit /b 1
