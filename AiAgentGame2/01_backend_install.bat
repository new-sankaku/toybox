@echo off
chcp 65001 > nul
echo ========================================
echo   Backend - 依存関係インストール
echo ========================================
echo.

cd /d "%~dp0\backend"
echo カレントディレクトリ: %cd%
echo.

echo Python バージョンを確認中...
python --version
if errorlevel 1 (
    echo エラー: Python がインストールされていません
    echo https://www.python.org/ からインストールしてください
    pause
    exit /b 1
)

echo.
echo 仮想環境を作成中...
if not exist "venv" (
    python -m venv venv
    echo 仮想環境を作成しました
) else (
    echo 仮想環境は既に存在します
)

echo.
echo 仮想環境をアクティベート中...
call venv\Scripts\activate.bat

echo.
echo 依存関係をインストール中...
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo エラー: インストールに失敗しました
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Backend インストール完了
echo ========================================
echo.
