@echo off
chcp 65001 > nul
setlocal
set "HERE=%~dp0"
set "PY=%HERE%vup\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo venv が見つかりません: %PY%
  echo vup\README.md の手順で venv を作ってください。
  pause
  exit /b 1
)
if "%~1"=="" (
  echo 動画ファイルか、動画の入ったフォルダを
  echo このバッチにドラッグ＆ドロップしてください。
  echo.
  echo   ・複数まとめて放り込めます
  echo   ・フォルダは直下の動画をまとめて処理します
  echo   ・出力は元の動画と同じ場所に _up を付けて出ます
  pause
  exit /b
)
"%PY%" "%HERE%vup\vup.py" %* --model sd-fast --scale 2
pause
