@echo off
chcp 65001 > nul
echo ========================================
echo   LangGraph Studio - キャッシュクリア
echo ========================================
echo.

cd /d "%~dp0"

echo Electronキャッシュをクリアしています...
echo.

:: Electronのユーザーデータパス（Windows）
set ELECTRON_CACHE=%APPDATA%\langgraph-studio

if exist "%ELECTRON_CACHE%" (
    echo キャッシュディレクトリを削除: %ELECTRON_CACHE%
    rmdir /s /q "%ELECTRON_CACHE%\cache" 2>nul
    rmdir /s /q "%ELECTRON_CACHE%\gpu-cache" 2>nul
    rmdir /s /q "%ELECTRON_CACHE%\GPUCache" 2>nul
    rmdir /s /q "%ELECTRON_CACHE%\session" 2>nul
    rmdir /s /q "%ELECTRON_CACHE%\Code Cache" 2>nul
    echo 完了
) else (
    echo キャッシュディレクトリが見つかりません
)

echo.

:: ビルド出力もクリアするか確認
set /p CLEAN_BUILD="ビルド出力 (out/) もクリアしますか？ [y/N]: "
if /i "%CLEAN_BUILD%"=="y" (
    echo.
    echo ビルド出力をクリアしています...
    if exist "out" rmdir /s /q "out"
    echo 完了
)

echo.
echo ========================================
echo   クリア完了
echo ========================================
echo.

pause
