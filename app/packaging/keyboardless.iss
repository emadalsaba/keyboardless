; keyboardless.iss -- مثبّت Keyboardless (بدون كيبورد) لوندوز.
;
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" app\packaging\keyboardless.iss
;
; المبادئ الثلاثة التي بُني عليها، بناءً على طلب عماد:
;   1. لا أسئلة تُشتّت المستخدم: لا صفحات مسار ولا مجلدات برامج — «التالي ثم تثبيت».
;   2. تنزيل النموذج **تلقائي** إلى المسار المخصص (%LOCALAPPDATA%\Keyboardless)
;      مع سطر حالة واحد يشرح ما يجري.
;   3. إعادة التثبيت لا تُنزّل 100MB مرة أخرى: التنزيل يعمل فقط إن كان النموذج غائبًا.
;
; التطبيق نفسه صغير (151MB) والنموذج (100MB تنزيل) يأتي من مصدره الأصلي
; (alphacephei.com/vosk) — وهو مجاني ومفتوح المصدر (Apache-2.0).

#define AppName "Keyboardless"
#define AppNameAr "بدون كيبورد"
#define AppVersion "1.0.2"
#define AppPublisher "عماد السبع"
#define AppPublisherAr "المبرمج عماد السبع"
#define AppURL "https://www.linkedin.com/in/emad-alsaba"
; الإهداء: يظهر في شاشة الترحيب — راجع branding.DEDICATION_AR
#define Dedication "أحتسبه عند ربي صدقةً عني وعن والديّ وأهلي."
; A line that *starts* with '#' is read by the preprocessor as a directive, and
; '#' inside a #define is an illegal character -- so Pascal's #13#10 stays on the
; line it belongs to and never begins one (a test guards this).
#define ExeName "Keyboardless.exe"
#define BuildDir "..\..\dist\Keyboardless"

[Setup]
AppId={{7F3C2A18-9D4E-4B77-8E21-5C0A6B9F4D13}
AppName={#AppName} ({#AppNameAr})
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} - إملاء صوتي عربي بدون إنترنت
VersionInfoProductName={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableWelcomePage=no
AllowNoIcons=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=Keyboardless-Setup-{#AppVersion}
SetupIconFile=keyboardless.ico
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
; Default.isl = English. Arabic messages would need a translation file shipped
; alongside; the screens here are three lines long, and the Arabic explanations
; are in the task and status strings below.
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon} — {#AppNameAr}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; the whole packaged app: the exe plus everything PyInstaller bundled with it
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName} ({#AppNameAr})"; Filename: "{app}\{#ExeName}"
Name: "{group}\إلغاء تثبيت {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName} ({#AppNameAr})"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
; ---- the automatic part: no question, one clear status line -----------------
Filename: "{app}\{#ExeName}"; Parameters: "--cli --ensure-model"; \
  StatusMsg: "يُنزَّل نموذج اللغة العربية (100MB تقريبًا) إلى مجلد التطبيق — لا تُغلق النافذة"; \
  Flags: runhidden waituntilterminated; Check: ModelMissing
; ---- optional: start it now -------------------------------------------------
Filename: "{app}\{#ExeName}"; Description: "تشغيل {#AppName} الآن"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The model lives outside {app}: 287MB would stay behind for ever otherwise.
; Settings and log are deliberately kept, so reinstalling does not push the user
; back to default hotkeys (and does not re-download the model either).
Type: filesandordirs; Name: "{localappdata}\Keyboardless\models"

[Code]
{ Is the Arabic model already on this machine? Then skip the 100MB download. }
function ModelMissing(): Boolean;
var
  Conf: String;
begin
  Conf := ExpandConstant('{localappdata}\Keyboardless\models\vosk-model-small-ar-0.3\conf');
  Result := not DirExists(Conf);
end;

procedure InitializeWizard();
begin
  { One sentence, up front, so the model download is never a surprise. }
  WizardForm.WelcomeLabel2.Caption :=
    'سيُثبَّت Keyboardless (بدون كيبورد) على هذا الجهاز.' + #13#10 + #13#10 +
    'إملاء صوتي عربي يعمل بلا إنترنت: التعرف يتم على جهازك.' + #13#10 +
    'التطبيق صغير، وسينزّل نموذج اللغة العربية (100MB تقريبًا) تلقائيًا أثناء التثبيت.' + #13#10 + #13#10 +
    '{#Dedication}';
end;
