@echo off
chcp 65001 > nul
echo ========================================
echo   LangGraph Studio - プレビュー実行
echo ========================================
echo.

cd /d "%~dp0"

if not exist "out\renderer\index.html" (
    echo ビルドが見つかりません。先にビルドを実行します...
    call build.bat
)

echo.
echo Electronアプリをプレビューモードで起動します...
echo.

call npm run preview

pause
