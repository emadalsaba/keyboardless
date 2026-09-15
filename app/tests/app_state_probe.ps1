# app_state_probe.ps1 -- أين يعيش النموذج فعلًا في النسخة المثبَّتة؟
#
#   powershell -ExecutionPolicy Bypass -File app\tests\app_state_probe.ps1
#
# يجيب على سؤال واحد بدقّة: أي مجلد نماذج تراه النسخة المثبَّتة، وما داخله، وما
# تقوله هي نفسها عبر `--cli --models` (وخرجها المحفوظ في cli-last.txt).
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = ""
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

if (-not $OutFile) { $OutFile = Join-Path $Root "app\app_state_probe.txt" }
$lines = New-Object System.Collections.Generic.List[string]
$exe = Join-Path $Root "dist\Keyboardless\Keyboardless.exe"
$dist = Join-Path $Root "dist\Keyboardless"
$data = Join-Path $env:LOCALAPPDATA "Keyboardless"
$userModels = Join-Path $data "models"
$distModels = Join-Path $dist "models"

function Describe([string] $path, [string] $label) {
    $lines.Add("--- ${label}: $path")
    if (-not (Test-Path $path)) { $lines.Add("  MISSING"); return }
    $files = @(Get-ChildItem $path -Recurse -File -Force -ErrorAction SilentlyContinue)
    $sum = ($files | Measure-Object -Property Length -Sum).Sum
    if (-not $sum) { $sum = 0 }
    $lines.Add("  files: $($files.Count) · size: $([math]::Round($sum / 1MB, 1)) MB")
    foreach ($item in (Get-ChildItem $path -Force -ErrorAction SilentlyContinue | Select-Object -First 8)) {
        $lines.Add("    $(if ($item.PSIsContainer) { 'dir ' } else { 'file' }) $($item.Name)")
    }
}

$lines.Add("user models folder exists : $(Test-Path $userModels)")
$lines.Add("dist models folder exists : $(Test-Path $distModels)")
$lines.Add("dist folder layout (top level):")
foreach ($item in (Get-ChildItem $dist -Force -ErrorAction SilentlyContinue | Select-Object -First 10)) {
    $lines.Add("    $(if ($item.PSIsContainer) { 'dir ' } else { 'file' }) $($item.Name)")
}

Describe $userModels "user models"
Describe $distModels "dist models"
Describe (Join-Path $userModels "vosk-model-small-ar-0.3") "the default model in the user folder"

# what the packaged app itself thinks, and its saved output
$p = Start-Process -FilePath $exe -ArgumentList "--cli", "--models" -Wait -PassThru -WindowStyle Hidden
$lines.Add("--cli --models exit code: $($p.ExitCode)")
$cliLog = Join-Path $data "cli-last.txt"
if (Test-Path $cliLog) {
    $lines.Add("--- cli-last.txt ---")
    foreach ($line in ([IO.File]::ReadAllText($cliLog, [Text.Encoding]::UTF8) -split "`r?`n")) {
        if ($line.Trim()) { $lines.Add($line) }
    }
}

Set-Content -LiteralPath $OutFile -Value $lines -Encoding UTF8
Write-Output "report: $OutFile"
