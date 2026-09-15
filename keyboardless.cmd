@echo off
chcp 65001 >nul
rem keyboardless.cmd -- الإملاء الصوتي العربي المباشر (بدون إنترنت).
rem شغّله بالنقر المزدوج، ثم اضغط اختصار الإملاء (يُقرأ من app\config.json) وابدأ الكلام.
cd /d "%~dp0"

echo ============================================
echo   Keyboardless (بدون كيبورد) -- إملاء صوتي عربي بدون إنترنت
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [!] لم أجد البيئة .venv -- نفّذ أولاً:
    echo     powershell -ExecutionPolicy Bypass -File app\install_windows.ps1
    pause
    exit /b 1
)

if not exist "models" (
    echo [!] لم أجد مجلد models -- نفّذ أولاً:
    echo     powershell -ExecutionPolicy Bypass -File app\install_windows.ps1
    pause
    exit /b 1
)

rem الاختصار يأتي من app\config.json وحده (لا تكرار هنا: التكرار هو ما جعل
rem الاختصار القديم يبقى معلنًا بعد تغييره). for /f مع مسار مُنصّص داخل cmd
rem يفشل بـ "cannot find the path specified"، لذا نكتب الملف ثم نطبعه.
echo   الاختصارات (من app\config.json -- غيّرها بأمر --set-hotkey):
set "ARKEYS=%TEMP%\keyboardless-keys.txt"
".venv\Scripts\python.exe" "app\ar_dictate.py" --print-hotkeys > "%ARKEYS%" 2>nul
if exist "%ARKEYS%" (
    type "%ARKEYS%"
    del "%ARKEYS%" >nul 2>&1
) else (
    echo   [!] تعذّر قراءة الاختصارات -- شغّل keyboardless-check.cmd
)
echo     (ابدأ/أوقف الكلام  ·  بدّل فصحى/لهجة  ·  خروج)
echo.
echo   أول تشغيل يحمّل نموذج الصوت (10-30 ثانية) قبل أن يستجيب الاختصار.
echo   اترك هذه النافذة مفتوحة، وانقر على البرنامج الذي تريد الكتابة فيه.
echo.

".venv\Scripts\python.exe" "app\ar_dictate.py" --profile fast %*
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" (
    echo [!] توقف Keyboardless برمز خطأ %RC%. آخر أسطر السجل:
    if exist "app\dictate.log" powershell -NoProfile -Command "Get-Content -LiteralPath 'app\dictate.log' -Tail 15 -Encoding UTF8"
    echo.
    echo     للتشخيص الكامل: انقر keyboardless-check.cmd
) else (
    echo توقف Keyboardless.
)
pause
