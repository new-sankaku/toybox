@echo off
chcp 65001 > nul
echo ========================================
echo   Frontend - 依存関係インストール
echo ========================================
echo.

cd /d "%~dp0\langgraph-studio"
echo カレントディレクトリ: %cd%
echo.

echo Node.js バージョンを確認中...
node --version
if errorlevel 1 (
    echo エラー: Node.js がインストールされていません
    echo https://nodejs.org/ からインストールしてください
    pause
    exit /b 1
)

echo.
echo npm バージョンを確認中...
call npm --version

echo.
echo 依存関係をインストール中...
echo.

call npm install

if errorlevel 1 (
    echo.
    echo エラー: インストールに失敗しました
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Frontend インストール完了
echo ========================================
echo.
