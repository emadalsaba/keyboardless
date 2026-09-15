@echo off
rem ===========================================================================
rem  keyboardless-gui.cmd -- opens the settings window (no console window).
rem
rem  Uses pythonw.exe on purpose: the window plus the tray icon are the whole
rem  user interface, so a black console box behind them would look broken.
rem  Everything it changes is written to app\config.json -- the same file the
rem  command-line launcher reads.
rem ===========================================================================
setlocal
cd /d "%~dp0"

set "PYW=%CD%\.venv\Scripts\pythonw.exe"
set "PY=%CD%\.venv\Scripts\python.exe"

if exist "%PYW%" (
    start "" "%PYW%" "app\gui.py" %*
    exit /b 0
)

rem Fall back to console python (with pythonw missing, a window is still better
rem than nothing), then to the system interpreter.
if exist "%PY%" (
    start "" "%PY%" "app\gui.py" %*
    exit /b 0
)

echo لم أجد بيئة التشغيل .venv في هذا المجلد.
echo شغّل أولًا:  powershell -ExecutionPolicy Bypass -File app\install_windows.ps1
pause
exit /b 1
