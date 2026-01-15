@echo off
chcp 65001 > nul
echo ========================================
echo   LangGraph Studio - 依存関係インストール
echo ========================================
echo.

cd /d "%~dp0"

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
npm --version

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
echo   インストール完了
echo ========================================
echo.
echo 次のコマンドで起動できます:
echo   dev.bat     - 開発サーバー起動
echo   build.bat   - プロダクションビルド
echo   preview.bat - ビルド後のプレビュー
echo.

pause
