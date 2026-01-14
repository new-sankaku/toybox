@echo off
chcp 65001 > nul

echo ========================================
echo   AI Agent Game Creator - Setup
echo ========================================
echo.

cd /d "%~dp0"

REM Python確認
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Pythonがインストールされていません
    pause
    exit /b 1
)

echo [OK] Python確認済み
python --version

REM venv作成
echo.
echo [INFO] venvを作成しています...
if exist "venv" (
    echo [INFO] 既存のvenvを削除します...
    rmdir /s /q venv
)
python -m venv venv
if errorlevel 1 (
    echo [ERROR] venvの作成に失敗しました
    pause
    exit /b 1
)
echo [OK] venv作成完了

REM アクティベート
call venv\Scripts\activate.bat

REM pip更新
echo.
echo [INFO] pipを更新しています...
python -m pip install --upgrade pip

REM 依存パッケージインストール
echo.
echo [INFO] 依存パッケージをインストールしています...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] パッケージのインストールに失敗しました
    pause
    exit /b 1
)

REM .env確認
echo.
if not exist ".env" (
    echo [INFO] .envファイルを作成します...
    copy .env.example .env > nul
    echo [WARNING] .envファイルにAPIキーを設定してください
)

echo.
echo ========================================
echo   セットアップ完了
echo ========================================
echo.
echo 次のステップ:
echo   1. .envファイルにAPIキーを設定
echo   2. run.bat を実行してゲームを作成
echo.
pause
