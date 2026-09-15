@echo off
chcp 65001 >nul
rem keyboardless-check.cmd -- فحص ذاتي بنقرة مزدوجة.
rem   keyboardless-check.cmd          فحص كامل (اختصارات + مايك + سجل)
rem   keyboardless-check.cmd quick    تخطّ الفحوصات التفاعلية
rem   keyboardless-check.cmd mic      فحص المايك فقط
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
set QUICK=%1

echo ============================================
echo   فحص Keyboardless (بدون كيبورد)
echo ============================================
echo.

if not exist "%PY%" (
    echo [x] لا توجد بيئة .venv
    echo     نفّذ: powershell -ExecutionPolicy Bypass -File app\install_windows.ps1
    goto :end
)
echo [v] البيئة موجودة: %PY%
"%PY%" --version

echo.
echo --- الاختصارات (يجب أن تظهر OK للثلاثة) ---
"%PY%" "app\ar_dictate.py" --check-hotkeys

echo.
echo --- النماذج ---
if exist "models" (dir /b models) else (echo [x] مجلد models غير موجود)

echo.
echo --- المكتبات ---
"%PY%" -c "import importlib.metadata as m; print('pynput', m.version('pynput'))"
"%PY%" -c "import sounddevice as sd; print('sounddevice OK')"
"%PY%" -c "import vosk; print('vosk OK')"

if /i "%QUICK%"=="mic" goto :mic
if /i "%QUICK%"=="quick" goto :skiptest

echo.
echo --- اختبار الالتقاط: اضغط أحد اختصارات الإملاء الظاهرة أعلاه (15 ثانية) ---
"%PY%" "app\tests\hook_test.py" --seconds 15
if errorlevel 1 (
    echo [!] لم يصل أي اختصار من الإعدادات. الأسباب الشائعة:
    echo     - برنامج آخر يحتجز نفس الاختصار ^(كلود يحتجز ctrl+alt+space افتراضيا^)
    echo       غيّره بأمر:  .venv\Scripts\python.exe app\ar_dictate.py --set-hotkey ctrl+alt+D
    echo     - البرنامج الذي تكتب فيه يعمل كمسؤول ^(Run as administrator^) والصندوق غير مرفوع
)

:skiptest
echo.
echo --- فحص المايك: تكلّم بصوت عادي 5 ثواني الآن ---
"%PY%" "app\ar_dictate.py" --mic-level 5
if errorlevel 1 (
    echo [!] لا يصل صوت أو لم يُتعرّف على كلام -- هذا سبب عدم ظهور النص.
    echo     - ويندوز: Settings ^> Privacy and security ^> Microphone ^> فعّل desktop apps
    echo     - اعرض المداخل:  .venv\Scripts\python.exe app\ar_dictate.py --list-devices
    echo     - ثم اختر رقمه:  .venv\Scripts\python.exe app\ar_dictate.py --device 3
)
goto :tail

:mic
echo --- فحص المايك: تكلّم بصوت عادي 5 ثواني الآن ---
"%PY%" "app\ar_dictate.py" --mic-level 5

:tail
echo.
echo --- آخر أسطر السجل ---
if exist "app\dictate.log" (powershell -NoProfile -Command "Get-Content -LiteralPath 'app\dictate.log' -Tail 12 -Encoding UTF8") else (echo لا يوجد سجل بعد -- شغّل keyboardless.cmd مرة واحدة)

:end
echo.
echo انتهى الفحص. اضغط Enter للإغلاق.
pause >nul
