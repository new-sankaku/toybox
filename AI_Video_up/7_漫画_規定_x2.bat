@echo off
chcp 65001 > nul
setlocal
set "HERE=%~dp0"
set "PY=%HERE%vup\venv\Scripts\python.exe"
set "MDL=%HERE%vup\models\manga\2x_MangaJaNai_1500p_V1_ESRGAN_90k.pth"
set "CLR=%HERE%vup\models\color\2x_IllustrationJaNai_V1_ESRGAN_120k.pth"
if not exist "%PY%" (
  echo venv が見つかりません: %PY%
  pause
  exit /b 1
)
if "%~1"=="" (
  echo 漫画の画像か、画像の入ったフォルダを
  echo このバッチにドラッグ＆ドロップしてください。
  echo.
  echo   ・フォルダは下位フォルダまで辿ります
  echo   ・出力は「フォルダ名_up」へ WebP で出ます
  echo   ・白黒ページは白黒のまま、カラーページは別モデルで処理します
  pause
  exit /b
)
"%PY%" "%HERE%vup\vup.py" %* --model "%MDL%" --img-color-model "%CLR%" --img-mono-model --scale 2 --no-trt
pause
