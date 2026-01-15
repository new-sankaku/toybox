@echo off
chcp 65001 > nul
echo ========================================
echo   LangGraph Studio - プロダクションビルド
echo ========================================
echo.

cd /d "%~dp0"

echo 依存関係を確認中...
if not exist "node_modules" (
    echo node_modules が見つかりません。npm install を実行します...
    call npm install
    if errorlevel 1 (
        echo エラー: npm install に失敗しました
        pause
        exit /b 1
    )
)

echo.
echo ビルドを開始します...
echo.

call npm run build

if errorlevel 1 (
    echo.
    echo ========================================
    echo   ビルド失敗
    echo ========================================
    pause
    exit /b 1
)

echo.
echo ========================================
echo   ビルド完了
echo ========================================
echo 出力先: out/
echo   - out/main/       (メインプロセス)
echo   - out/preload/    (プリロード)
echo   - out/renderer/   (レンダラー)
echo.

pause
