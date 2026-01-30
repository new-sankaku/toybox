@echo off
chcp 65001 > /dev/null

REM ANSI color codes
for /F %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
set "RED=%ESC%[31m"
set "GREEN=%ESC%[32m"
set "YELLOW=%ESC%[33m"
set "CYAN=%ESC%[36m"
set "RESET=%ESC%[0m"

echo ========================================
echo   Code Metrics - Lines of Code Analysis
echo ========================================
echo.

cd /d "%~dp0"

REM Check if cloc is available
where cloc >nul 2>&1
if %errorlevel% neq 0 (
    echo %YELLOW%cloc not found, using npx...%RESET%
    set "CLOC_CMD=npx cloc"
) else (
    set "CLOC_CMD=cloc"
)

set "REPORT_DIR=%~dp0reports"
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%"

set "TIMESTAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%"
set "TIMESTAMP=%TIMESTAMP: =0%"

echo %CYAN%[1/6] Project Overview%RESET%
echo.
%CLOC_CMD% --exclude-dir=node_modules,venv,.venv,dist,build,.git,.mypy_cache,__pycache__,.pytest_cache,.hypothesis,cache,playwright-report --exclude-ext=lock,png,jpg,jpeg,gif,svg,ico backend langgraph-studio
echo.

echo %CYAN%[2/6] Backend (Python)%RESET%
echo.
%CLOC_CMD% --exclude-dir=venv,.venv,.mypy_cache,__pycache__,.pytest_cache,.hypothesis,cache --include-lang=Python backend
echo.

echo %CYAN%[3/6] Frontend (TypeScript/JavaScript/CSS)%RESET%
echo.
%CLOC_CMD% --exclude-dir=node_modules,dist,build,playwright-report --include-lang=TypeScript,JavaScript,CSS langgraph-studio
echo.

echo %CYAN%[4/6] Config Files (YAML/TOML/INI/JSON)%RESET%
echo.
%CLOC_CMD% --exclude-dir=node_modules,venv,.venv,dist,build,.git,.mypy_cache,__pycache__,.pytest_cache,.hypothesis,cache,playwright-report --include-lang=YAML,TOML,INI,JSON backend langgraph-studio
echo.

echo %CYAN%[5/6] Documentation (Markdown/HTML)%RESET%
echo.
%CLOC_CMD% --exclude-dir=node_modules,venv,.venv,dist,build,.git,.mypy_cache,__pycache__,.pytest_cache,.hypothesis,cache,playwright-report --include-lang=Markdown,HTML backend langgraph-studio doc
echo.

echo %CYAN%[6/6] Generating Report...%RESET%
echo.

set "REPORT_FILE=%REPORT_DIR%\code_metrics_%TIMESTAMP%.md"

echo # Code Metrics Report > "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"
echo Generated: %date% %time% >> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"
echo ## Project Overview >> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
%CLOC_CMD% --exclude-dir=node_modules,venv,.venv,dist,build,.git,.mypy_cache,__pycache__,.pytest_cache,.hypothesis,cache,playwright-report --exclude-ext=lock,png,jpg,jpeg,gif,svg,ico backend langgraph-studio >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"

echo ## Backend (Python) >> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
%CLOC_CMD% --exclude-dir=venv,.venv,.mypy_cache,__pycache__,.pytest_cache,.hypothesis,cache --include-lang=Python backend >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"

echo ## Frontend (TypeScript/JavaScript/CSS) >> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
%CLOC_CMD% --exclude-dir=node_modules,dist,build,playwright-report --include-lang=TypeScript,JavaScript,CSS langgraph-studio >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"

echo ## Config Files (YAML/TOML/INI/JSON) >> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
%CLOC_CMD% --exclude-dir=node_modules,venv,.venv,dist,build,.git,.mypy_cache,__pycache__,.pytest_cache,.hypothesis,cache,playwright-report --include-lang=YAML,TOML,INI,JSON backend langgraph-studio >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"

echo ## Documentation (Markdown/HTML) >> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
%CLOC_CMD% --exclude-dir=node_modules,venv,.venv,dist,build,.git,.mypy_cache,__pycache__,.pytest_cache,.hypothesis,cache,playwright-report --include-lang=Markdown,HTML backend langgraph-studio doc >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"

echo ## By File (Top 50) >> "%REPORT_FILE%"
echo. >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"
%CLOC_CMD% --exclude-dir=node_modules,venv,.venv,dist,build,.git,.mypy_cache,__pycache__,.pytest_cache,.hypothesis,cache,playwright-report --exclude-ext=lock,png,jpg,jpeg,gif,svg,ico --by-file backend langgraph-studio | head -70 >> "%REPORT_FILE%"
echo ```>> "%REPORT_FILE%"

echo %GREEN%Report saved to: %REPORT_FILE%%RESET%
echo.

echo ========================================
echo   %GREEN%Code metrics completed!%RESET%
echo ========================================
echo.

pause
