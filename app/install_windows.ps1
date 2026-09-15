# install_windows.ps1 -- one-shot setup for ar-dictate on Windows.
#
#   powershell -ExecutionPolicy Bypass -File install_windows.ps1
#
# Run from an ordinary (non-elevated) PowerShell window. Nothing here needs
# Administrator: the app types into normal windows and the pynput hotkeys work
# unelevated.
#
# Notes learned the hard way:
#   * `uv venv --python 3.x` fails on machines where uv's *downloaded* Python
#     lives on an untrusted mount ("os error 448"). So create the venv with an
#     interpreter that is already installed (PyManager `py -3.x`) and only use
#     uv for the fast package install.
#   * Keep every path absolute: the SSH/non-interactive shell does not inherit
#     the interactive PATH.

[CmdletBinding()]
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $Model = "vosk-model-ar-mgb2-0.4",   # accurate; -FastModel also installed
    [string] $FastModel = "vosk-model-small-ar-0.3",
    [switch] $SkipDownload
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # curl-style progress redraw is very slow in PS
$modelUrl = "https://alphacephei.com/vosk/models"

function Say($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Say "paths"
$App = Join-Path $Root "app"
$Models = Join-Path $Root "models"
$Venv = Join-Path $Root ".venv"
New-Item -ItemType Directory -Force -Path $Root, $Models | Out-Null
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { throw "curl.exe not found (needs Windows 10 1803+)" }

# ---------------------------------------------------------------- interpreter
function Get-PythonExe {
    # 1) the py launcher with a concrete version (most reliable, pre-installed)
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        foreach ($v in @("-3.13", "-3.12", "-3.14", "-3.11")) {
            $exe = (& py.exe $v -c "import sys; print(sys.executable)" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) { return $exe.Trim() }
        }
    }
    # 2) a pythoncore install dropped by the Python Install Manager
    $candidates = Get-ChildItem "$env:LOCALAPPDATA\Python\pythoncore-*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    if ($candidates) { return $candidates[0].FullName }
    throw "no usable Python 3.11-3.14 found. Install one with:  py install 3.12"
}

Say "creating virtual environment"
if (Test-Path (Join-Path $Venv "Scripts\python.exe")) {
    Write-Host "already present: $Venv"
} else {
    $python = Get-PythonExe
    Write-Host "using interpreter: $python"
    & $python -m venv $Venv
}
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { throw "venv creation failed: $VenvPy missing" }

Say "installing packages"
$req = Join-Path $App "requirements.txt"
if (Get-Command uv.exe -ErrorAction SilentlyContinue) {
    & uv.exe pip install --python $VenvPy -r $req
} else {
    & $VenvPy -m pip install --upgrade pip
    & $VenvPy -m pip install -r $req
}

Say "models"
foreach ($m in @($Model, $FastModel)) {
    if ($SkipDownload) { continue }
    $dir = Join-Path $Models $m
    $name = "$m.zip"
    if (Test-Path $dir) { Write-Host "already unpacked: $m"; continue }
    $zip = Join-Path $Root $name
    Write-Host "downloading $name ..."
    & curl.exe -L --progress-bar -o $zip "$modelUrl/$name"
    Write-Host "unpacking $m ..."
    Expand-Archive -Path $zip -DestinationPath $Models -Force
    Remove-Item $zip -Force
}

# ------------------------------------------------------------------- launcher
Say "launcher"
# The launchers ship from a Linux checkout with LF endings; cmd.exe needs CRLF
# or the file dies silently before python ever runs. Normalize in place and
# verify, so the installed launcher can never be a dead one.
foreach ($name in @("keyboardless.cmd", "keyboardless-gui.cmd", "keyboardless-check.cmd")) {
    $p = Join-Path $Root $name
    if (-not (Test-Path $p)) { Write-Warning "launcher not found: $p"; continue }
    $text = [IO.File]::ReadAllText($p)
    [IO.File]::WriteAllText($p, ($text -replace "`r?`n", "`r`n"), (New-Object Text.UTF8Encoding($false)))
    $b = [IO.File]::ReadAllBytes($p)
    $loneLF = ($b | Where-Object { $_ -eq 10 }).Count - ($b | Where-Object { $_ -eq 13 }).Count
    if ($loneLF -ne 0) { throw "$name still has $loneLF LF-only line ending(s)" }
    Write-Host "normalized $p ($($b.Length) bytes, CRLF ok)"
}

Say "the hotkeys this install will listen on (read from app\config.json)"
& $VenvPy (Join-Path $App "ar_dictate.py") --print-hotkeys

Say "done"
# Never repeat the combinations here: this text is what the user reads first,
# and a stale literal (the old Claude-Desktop key) sent people to a key that
# does nothing. Ask the app instead. $cmd was also undefined and printed blank.
$launcher = Join-Path $Root "keyboardless.cmd"
$gui = Join-Path $Root "keyboardless-gui.cmd"
Write-Host @"
Next steps:
  1. Run the self test (no microphone needed):
       $VenvPy $App\ar_dictate.py --wav $Root\samples\test_msa.wav --injector stdout
  2. List microphones:      $VenvPy $App\ar_dictate.py --list-devices
  3. Start dictating:       $launcher      (or the Keyboardless desktop shortcut)
       the hotkeys are printed above and shown on the launcher's banner
       settings window:        $gui
  4. Type into Notepad first; some stores apps need the "clipboard" injector
     (edit $App\config.json -> "injector": "clipboard").
"@ -ForegroundColor Green
