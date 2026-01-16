@echo off
chcp 65001 > nul
echo ========================================
echo   AiAgentGame2 - 全コンポーネントインストール
echo ========================================
echo.

cd /d "%~dp0"

echo [1/2] バックエンドをインストール中...
echo.
call 01_backend_install.bat

echo.
echo [2/2] フロントエンドをインストール中...
echo.
call 11_frontend_install.bat

echo.
echo ========================================
echo   全てのインストールが完了しました
echo ========================================
echo.
echo 起動コマンド:
echo   20_run_all_mock.bat - Backend(mock) + Frontend を同時起動
echo.

pause
