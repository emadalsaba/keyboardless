# exe_probe.ps1 -- يتحقّق من نسخة المثبَّت (dist\Keyboardless\Keyboardless.exe) كما يستعملها المستخدم.
#
#   run_probe_interactive.ps1 -Script exe_probe.ps1 -Report exe_probe.txt
#
# What it answers, in order:
#   1. هل يعمل سطر الأوامر من الملف المبني (وهل كُتب ملف المخرجات للدعم)؟
#   2. أين نزّل النموذج فعلًا، وهل المسار المخصص صحيح؟
#   3. هل تُرسم النافذة بخطوط سطح المكتب؟
#   4. هل تبقى النافذة حيّة (أيقونة جانبية) بدل أن تموت فورًا؟
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "exe_probe.txt",
    [int]    $WindowSeconds = 12
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$lines = New-Object System.Collections.Generic.List[string]
$exe = Join-Path $Root "dist\Keyboardless\Keyboardless.exe"
$data = Join-Path $env:LOCALAPPDATA "Keyboardless"
$cliLog = Join-Path $data "cli-last.txt"
$shot = Join-Path $Root "app\exe_shot.png"

$lines.Add("root: $Root")
$lines.Add("exe exists: $(Test-Path $exe)  ($(if (Test-Path $exe) { [math]::Round((Get-Item $exe).Length/1KB,0) } else { 0 }) KB)")
$lines.Add("data folder: $data (exists: $(Test-Path $data))")

function Run-Cli([string[]] $cliArgs) {
    # a windowed exe is not waited on by cmd, and Start-Process is what an
    # installer does -- so this is the honest way to run it
    $p = Start-Process -FilePath $exe -ArgumentList $cliArgs -Wait -PassThru -WindowStyle Hidden
    return $p.ExitCode
}

$code = Run-Cli @("--cli", "--models")
$lines.Add("--cli --models exit=$code")
if (Test-Path $cliLog) {
    $lines.Add("--- cli-last.txt (UTF-8) ---")
    foreach ($line in ([IO.File]::ReadAllText($cliLog, [Text.Encoding]::UTF8) -split "`r?`n")) {
        if ($line.Trim()) { $lines.Add($line) }
    }
} else {
    $lines.Add("cli-last.txt MISSING: a support request would have nothing to read")
}

$lines.Add("--- models folder ---")
$models = Join-Path $data "models"
if (Test-Path $models) {
    Get-ChildItem $models -Directory | ForEach-Object {
        $size = [math]::Round(((Get-ChildItem $_.FullName -Recurse -File |
                Measure-Object Length -Sum).Sum / 1MB), 1)
        $lines.Add("  $($_.Name) — $size MB")
    }
} else {
    $lines.Add("  MISSING: $models")
}

# the window: render it with the real desktop fonts, then keep it running for a
# while to prove the tray keeps it alive instead of the process dying
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$code = Run-Cli @("--shot", $shot, "--no-tray")
$bytes = if (Test-Path $shot) { (Get-Item $shot).Length } else { 0 }
$lines.Add("--shot exit=$code bytes=$bytes")

$proc = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds $WindowSeconds
$alive = -not $proc.HasExited
$lines.Add("window alive after ${WindowSeconds}s: $alive (pid $($proc.Id))")
if ($alive) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }

# the frozen app's own log is the proof that it found the downloaded model and
# bound the hotkeys -- without reading it, "the window opened" proves little
$log = Join-Path $data "dictate.log"
$lines.Add("--- the packaged app's log (dictate.log) ---")
if (Test-Path $log) {
    foreach ($line in (Get-Content $log -Tail 12 -Encoding UTF8)) { $lines.Add($line) }
} else {
    $lines.Add("  no log yet at $log")
}

Set-Content -LiteralPath $OutFile -Value $lines -Encoding UTF8
