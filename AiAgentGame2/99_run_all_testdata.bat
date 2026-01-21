@echo off
chcp 65001 > /dev/null
powershell -ExecutionPolicy Bypass -File "%~dp0run_testdata.ps1"
