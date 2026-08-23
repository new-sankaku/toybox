@echo off
chcp 65001 > nul
setlocal
set "HERE=%~dp0"
set "VENV=%HERE%vup\venv"

echo AI_Video_up の Python 環境を作ります。
echo   場所 : %VENV%
echo   元   : %HERE%requirements.txt
echo.
echo   ・Python 3.10 と NVIDIA driver(CUDA 12.6 相当)が要ります
echo   ・torch だけで 3GB ほど落とします。10〜20分ほど掛かります
echo   ・model の重みは初回実行時に自動で落ちます(この bat では落としません)
echo.
pause

where py > nul 2>&1
if errorlevel 1 (
  echo Python launcher(py)が見つかりません。Python 3.10 を入れてください。
  pause
  exit /b 1
)

if exist "%VENV%\Scripts\python.exe" (
  echo 既に venv があります。中身の更新だけ行います。
) else (
  py -3.10 -m venv "%VENV%"
  if errorlevel 1 (
    echo venv を作れませんでした。Python 3.10 が入っているか確認してください。
    pause
    exit /b 1
  )
)

"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -r "%HERE%requirements.txt" ^
  --extra-index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 (
  echo 導入に失敗しました。上の error を確認してください。
  pause
  exit /b 1
)

echo.
"%VENV%\Scripts\python.exe" -c "import torch;print('torch',torch.__version__,'CUDA',torch.cuda.is_available(),torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
echo.
echo 出来ました。1〜8 の bat に動画や画像をドラッグ＆ドロップしてください。
pause
