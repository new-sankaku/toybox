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
  echo   ・コマ数を元の2倍にします（アニメなら約48fps）
  echo   ・複数まとめて放り込めます
  echo   ・フォルダは直下の動画をまとめて処理します
  echo   ・出力は元の動画と同じ場所に _47fps を付けて出ます
  echo   ・音声と字幕は元のまま入ります
  echo.
  echo   ・OP・ED には掛けないでください。
  echo     元から動きが細かいので効果が無く、むしろ残像が出ます。
  echo   ・時間がかかります。23分のアニメ1話で7分半ほどです。
  echo   ・処理中もパソコンを使いたい時は、このバッチの最後の行の
  echo     末尾に --低負荷 を足してください。1話 9分半ほどに延びる代わりに
  echo     CPU の使用が 4割ほどに減ります。
  pause
  exit /b
)
"%PY%" "%HERE%vfi2\vfi.py" %* --fps x2 --model v4.6
pause
