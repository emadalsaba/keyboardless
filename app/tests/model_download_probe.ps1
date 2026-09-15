# model_download_probe.ps1 -- لماذا لم يُنزَّل النموذج في النسخة المثبَّتة؟
#
#   powershell -ExecutionPolicy Bypass -File app\tests\model_download_probe.ps1
#
# يسرد مجلد بيانات التطبيق كاملًا، ثم يشغّل التنزيل ويطبع خرج الملف المبني من
# cli-last.txt (وهو سجل التنزيل نفسه)، ثم يسرد النتيجة.
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "",
    [int]    $WaitMinutes = 25
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

if (-not $OutFile) { $OutFile = Join-Path $Root "app\model_download_probe.txt" }
$lines = New-Object System.Collections.Generic.List[string]
$exe = Join-Path $Root "dist\Keyboardless\Keyboardless.exe"
$data = Join-Path $env:LOCALAPPDATA "Keyboardless"
$cliLog = Join-Path $data "cli-last.txt"

function Show-Tree([string] $path, [string] $title) {
    # ${title} with braces: "$title:" reads as a drive-qualified variable and
    # PowerShell refuses to parse it ("InvalidVariableReferenceWithDrive")
    $lines.Add("--- ${title}: $path")
    if (-not (Test-Path $path)) { $lines.Add("  MISSING"); return }
    $dirs = @(Get-ChildItem $path -Recurse -Directory -ErrorAction SilentlyContinue)
    $files = @(Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue)
    $lines.Add("  directories: $($dirs.Count) · files: $($files.Count) · " +
               "size: $([math]::Round((($files | Measure-Object Length -Sum).Sum)/1MB,2)) MB")
    foreach ($d in ($dirs | Select-Object -First 6)) {
        $rel = $d.FullName.Substring($path.Length).TrimStart('\')
        $n = @(Get-ChildItem $d.FullName -File -ErrorAction SilentlyContinue).Count
        $lines.Add("    dir  $rel  (files: $n)")
    }
    foreach ($f in ($files | Select-Object -First 6)) {
        $rel = $f.FullName.Substring($path.Length).TrimStart('\')
        $lines.Add("    file $rel  ($([math]::Round($f.Length/1MB,2)) MB)")
    }
}

Show-Tree $data "app data"
Show-Tree (Join-Path $data "models") "models"

$lines.Add("--- running: Keyboardless.exe --cli --ensure-model")
$p = Start-Process -FilePath $exe -ArgumentList "--cli", "--ensure-model" -PassThru `
     -WindowStyle Hidden
if (-not $p.WaitForExit($WaitMinutes * 60000)) {
    $lines.Add("NOTE: still running after $WaitMinutes minutes - killing it")
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
} else {
    $lines.Add("exit code: $($p.ExitCode)")
}

if (Test-Path $cliLog) {
    $lines.Add("--- cli-last.txt (the download's own log) ---")
    foreach ($line in ([IO.File]::ReadAllText($cliLog, [Text.Encoding]::UTF8) -split "`r?`n")) {
        if ($line.Trim()) { $lines.Add($line) }
    }
} else {
    $lines.Add("cli-last.txt MISSING")
}

Show-Tree (Join-Path $data "models") "models after the download"
Set-Content -LiteralPath $OutFile -Value $lines -Encoding UTF8
Write-Output "report: $OutFile"
