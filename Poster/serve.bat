@echo off
setlocal
set PORT=%1
if "%PORT%"=="" set PORT=8080
echo POSTER FORGE  http://localhost:%PORT%/
start "" http://localhost:%PORT%/
python -m http.server %PORT% --directory "%~dp0"
endlocal
