@echo off
setlocal
set "RESULT=0"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
reg query "%RUN_KEY%" /v SelectTrans >nul 2>&1
if not errorlevel 1 (
    reg delete "%RUN_KEY%" /v SelectTrans /f >nul 2>&1
    if errorlevel 1 set "RESULT=1"
)
rem 旧版本用 Translator 作为值名，升级后一并清掉。
reg delete "%RUN_KEY%" /v Translator /f >nul 2>&1
set "LEGACY_STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\translator.vbs"
if exist "%LEGACY_STARTUP%" (
    del "%LEGACY_STARTUP%"
    if exist "%LEGACY_STARTUP%" set "RESULT=1"
)
if "%RESULT%"=="0" (
    echo [OK] SelectTrans startup disabled.
) else (
    echo [ERROR] Could not remove a startup entry. Check permissions.
)
if /i not "%~1"=="--no-pause" pause
exit /b %RESULT%
