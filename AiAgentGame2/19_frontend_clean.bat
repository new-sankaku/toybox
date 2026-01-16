@echo off
chcp 65001 > nul
echo ========================================
echo   Frontend - node_modules 削除
echo ========================================
echo.

cd /d "%~dp0\langgraph-studio"

echo node_modules を削除します...
if exist "node_modules" (
    rmdir /s /q node_modules
    echo 削除完了
) else (
    echo node_modules は存在しません
)

echo.
pause
