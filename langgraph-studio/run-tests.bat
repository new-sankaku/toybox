@echo off
chcp 65001 > nul
setlocal

echo ========================================
echo  Playwright E2E テスト
echo ========================================
echo.

cd /d "%~dp0"

if "%1"=="" (
    echo 全テスト実行中...
    npx playwright test
) else if "%1"=="ui" (
    echo UIモードで起動中...
    npx playwright test --ui
) else if "%1"=="report" (
    echo レポート表示中...
    npx playwright show-report
) else if "%1"=="project" (
    echo ProjectViewテスト実行中...
    npx playwright test project.spec.ts
) else if "%1"=="checkpoints" (
    echo CheckpointsViewテスト実行中...
    npx playwright test checkpoints.spec.ts
) else if "%1"=="data" (
    echo DataViewテスト実行中...
    npx playwright test data.spec.ts
) else if "%1"=="logs" (
    echo LogsViewテスト実行中...
    npx playwright test logs.spec.ts
) else if "%1"=="headed" (
    echo ブラウザ表示モードで実行中...
    npx playwright test --headed
) else if "%1"=="debug" (
    echo デバッグモードで実行中...
    npx playwright test --debug
) else (
    echo 使用方法:
    echo   run-tests.bat           全テスト実行
    echo   run-tests.bat ui        UIモードで起動
    echo   run-tests.bat report    レポート表示
    echo   run-tests.bat headed    ブラウザ表示モード
    echo   run-tests.bat debug     デバッグモード
    echo   run-tests.bat project   ProjectViewのみ
    echo   run-tests.bat checkpoints  CheckpointsViewのみ
    echo   run-tests.bat data      DataViewのみ
    echo   run-tests.bat logs      LogsViewのみ
)

echo.
echo ========================================
endlocal
