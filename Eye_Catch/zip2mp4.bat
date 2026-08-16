@echo off
rem PNG連番 zip を mp4 に変換する。zip をこの bat にドロップするか、そのまま実行する。
setlocal

rem 画質や codec を変えたい場合はここに書く（例: --crf 16 --codec nvenc --force）
set "OPTS="

set "SCRIPT=%~dp0zip2mp4.py"
if not exist "%SCRIPT%" goto :noscript

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if defined PY goto :run
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :run
where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if not defined PY goto :nopython

:run
if "%~1"=="" goto :all
"%PY%" "%SCRIPT%" %OPTS% %*
goto :done

:all
echo ドロップされた file が無いため、この folder の zip をすべて変換します。
pushd "%~dp0"
"%PY%" "%SCRIPT%" %OPTS%
popd
goto :done

:noscript
echo zip2mp4.py が bat と同じ folder にありません: "%SCRIPT%"
goto :end

:nopython
echo python が PATH にありません。
goto :end

:done
if errorlevel 1 echo 変換に失敗した file があります。上の出力を確認してください。

:end
echo.
pause
endlocal
