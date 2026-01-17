@echo off
chcp 65001 > nul
echo ========================================
echo   Frontend - Rebuild
echo ========================================
echo.

cd /d "%~dp0\langgraph-studio"

if not exist "node_modules" (
    echo エラー: node_modulesが見つかりません
    echo 先に 11_frontend_install.bat を実行してください
    pause
    exit /b 1
)

echo ビルド中...
echo.

call npm run build

if %errorlevel% neq 0 (
    echo.
    echo ビルドに失敗しました
    pause
    exit /b 1
)

echo.
echo ========================================
echo   ビルド完了
echo ========================================
echo.
echo out/ ディレクトリに出力されました
echo.

pause
