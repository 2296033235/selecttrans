@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Run setup.bat first.
    if /i not "%~1"=="--no-pause" pause
    exit /b 1
)
".venv\Scripts\python.exe" selecttrans.py
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo [ERROR] SelectTrans stopped with an error.
    if /i not "%~1"=="--no-pause" pause
)
exit /b %RESULT%
