# build_windows.ps1 -- يبني نسخة ويندوز الجاهزة (Keyboardless.exe).
#
#   powershell -ExecutionPolicy Bypass -File app\packaging\build_windows.ps1
#
# Produces dist\Keyboardless\ with the executable and everything it needs EXCEPT
# the recogniser model: the installer downloads that into the user's folder, so
# this archive stays small.
#
# Flags:
#   -SkipClean   keep the previous build folder (faster, for repeat runs)
[CmdletBinding()]
param(
    [string] $Root = "",
    [switch] $SkipClean,
    [switch] $Installer          # also compile the Inno Setup installer (.exe)
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not $Root) { $Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$App = Join-Path $Root "app"
$Spec = Join-Path $App "packaging\keyboardless.spec"

function Say($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

if (-not (Test-Path $Py)) { throw "no interpreter at $Py -- run app\install_windows.ps1 first" }
Say "icon"
& $Py (Join-Path $App "packaging\make_icon.py")

Say "bundling with PyInstaller"
Push-Location $Root
try {
    $pyArgs = @("-m", "PyInstaller", $Spec, "--noconfirm", "--distpath", (Join-Path $Root "dist"),
              "--workpath", (Join-Path $Root "build"))
    if (-not $SkipClean) { $pyArgs += "--clean" }
    & $Py @pyArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

$out = Join-Path $Root "dist\Keyboardless"
$exe = Join-Path $out "Keyboardless.exe"
if (-not (Test-Path $exe)) { throw "build finished but $exe is missing" }

$size = [math]::Round(((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
$exeSize = [math]::Round((Get-Item $exe).Length / 1KB, 0)
Say "result"
Write-Host "  exe      : $exe ($exeSize KB)"
Write-Host "  folder   : $out ($size MB تجميعيًا)"
Write-Host "  النموذج  : غير مضمّن — يُنزَّل إلى %LOCALAPPDATA%\Keyboardless\models"
if ($Installer) {
    Say "installer (Inno Setup)"
    # winget installs it per user, a manual install goes to Program Files: look in
    # all three places instead of assuming one
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"))
    $iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $iscc) {
        Write-Warning "Inno Setup غير مثبّت: ثبّته بـ winget install JRSoftware.InnoSetup ثم أعد -Installer"
    } else {
        & $iscc (Join-Path $App "packaging\keyboardless.iss")
        if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }
        $setup = Get-ChildItem (Join-Path $Root "dist\installer\*.exe") |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($setup) {
            Write-Host "  المثبّت : $($setup.FullName) ($([math]::Round($setup.Length/1MB,1)) MB)" -ForegroundColor Green
        }
    }
}

Write-Host "`n  جرّب النسخة:  & '$exe' --cli --about" -ForegroundColor Green
Write-Host "  ثم الواجهة:   & '$exe'" -ForegroundColor Green
