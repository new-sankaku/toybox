@echo off
chcp 65001 > nul
echo ========================================
echo   AiAgentGame2 Backend - 依存関係インストール
echo ========================================
echo.

cd /d "%~dp0"
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
echo   インストール完了
echo ========================================
echo.
echo 次のコマンドで起動できます:
echo   01_run_mock.bat     - モックモードで起動
echo   02_run_langgraph.bat - LangGraphモードで起動
echo.
echo .env ファイルを設定してください:
echo   copy .env.example .env
echo   (ANTHROPIC_API_KEY を設定)
echo.

pause
