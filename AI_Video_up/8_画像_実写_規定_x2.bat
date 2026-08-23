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
  echo 実写の画像か、画像の入ったフォルダを
  echo このバッチにドラッグ＆ドロップしてください。
  echo.
  echo   ・フォルダは下位フォルダまで辿ります
  echo   ・出力は「フォルダ名_up」へ WebP で出ます
  echo   ・アニメ・イラストには 1 か 7 のバッチを使ってください
  echo   ・GPUは半分までしか使いません（録画中でも流せます）
  pause
  exit /b
)
"%PY%" "%HERE%vup\vup.py" %* --model photo --scale 2 --no-trt --gpu-share 50
pause
