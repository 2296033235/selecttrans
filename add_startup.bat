@echo off
setlocal
cd /d "%~dp0"
set "RESULT=0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Run setup.bat first.
    goto error
)
".venv\Scripts\python.exe" -c "import selecttrans as t; t.set_startup(True); raise SystemExit(0 if t.is_startup_enabled() else 1)"
if errorlevel 1 goto error
echo [OK] Enabled startup for this copy of SelectTrans.
echo You can also manage this from the system tray menu.
goto finish

:error
echo [ERROR] Could not enable startup.
set "RESULT=1"

:finish
if /i not "%~1"=="--no-pause" pause
exit /b %RESULT%
