@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ========================================
echo   AI Agent Game Creator
echo ========================================
echo.

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [INFO] venvが見つかりません。作成します...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] venvの作成に失敗しました
        pause
        exit /b 1
    )
    echo [OK] venv作成完了
)

call venv\Scripts\activate.bat

pip show langgraph > nul 2>&1
if errorlevel 1 (
    echo [INFO] 依存パッケージをインストールします...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] パッケージのインストールに失敗しました
        pause
        exit /b 1
    )
    echo [OK] インストール完了
)

if not exist ".env" (
    echo [WARNING] .envファイルが見つかりません
    copy .env.example .env > nul
    echo [INFO] .envファイルを作成しました。APIキーを設定してください。
    notepad .env
    pause
    exit /b 1
)

REM request.txtからリクエストを読み込んで実行
set /p REQUEST=<request.txt
python -m src.main "%REQUEST%"

echo.
if errorlevel 1 (
    echo [ERROR] 実行中にエラーが発生しました
) else (
    echo [OK] 完了しました
)

REM 完了音を鳴らす
powershell -Command "(New-Object Media.SoundPlayer 'C:\Windows\Media\tada.wav').PlaySync()"

pause
