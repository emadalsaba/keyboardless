# run_probe_interactive.ps1 -- SSH lands in a NON-interactive session where
# SendInput is denied (no desktop), so the probe must be launched on the real
# desktop session. This script does that with a scheduled task (/IT), captures
# the probe's console output to <Report>.log, and reports what it wrote.
#
#   powershell -ExecutionPolicy Bypass -File run_probe_interactive.ps1 [-Script probe.ps1] `
#       [-Report out.txt] [-ExtraArgs "-ReadySec 90"] [-WaitSec 300]

param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [ValidateSet("msa", "dialect")][string] $Mode = "msa",
    [string] $Wav,
    [string] $Model,
    [int] $WaitSec = 150,
    [string] $Script = "inject_e2e_probe.ps1",
    [string] $Report = "probe_result.txt",
    [string] $ExtraArgs = ""
)

$probe = Join-Path $Root "app\tests\$Script"
$out   = Join-Path $Root "app\$Report"
$log   = Join-Path $Root "app\$Report.log"
$task  = "arDictateProbe"
Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue

Write-Host ("ssh session interactive: {0}; explorer running: {1}" -f `
    [System.Environment]::UserInteractive, `
    [bool](Get-Process -Name explorer -ErrorAction SilentlyContinue)) -ForegroundColor Cyan

$inner = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$probe`" -Root `"$Root`" -OutFile `"$out`""
if ($Script -like "inject_e2e_probe*") {
    $inner += " -Mode $Mode"
    if ($Wav)   { $inner += " -Wav `"$Wav`"" }
    if ($Model) { $inner += " -Model `"$Model`"" }
}
if ($ExtraArgs) { $inner += " $ExtraArgs" }

# schtasks /TR cannot survive nested quotes (it split on '-NoProfile' and refused
# to create the task). So: generate a wrapper .cmd in a path WITHOUT spaces and
# point /TR at it — the wrapper owns the quoting and the console redirection.
$wrapper = Join-Path $Root "app\tests\_run_probe.cmd"
$lines = @(
    "@echo off",
    "chcp 65001 >nul",
    "$inner > `"$log`" 2>&1"
)
Set-Content -LiteralPath $wrapper -Value $lines -Encoding ASCII

Write-Host "creating interactive task..." -ForegroundColor Cyan
schtasks /Create /TN $task /TR $wrapper /SC ONCE /ST 23:59 /IT /F | Out-Host
schtasks /Run /TN $task | Out-Host

$sw = [Diagnostics.Stopwatch]::StartNew()
while (-not (Test-Path $out) -and $sw.Elapsed.TotalSeconds -lt $WaitSec) {
    Start-Sleep -Seconds 3
}
$elapsed = [int]$sw.Elapsed.TotalSeconds

Write-Host ""
Write-Host "=== PROBE REPORT ($out) ===" -ForegroundColor Green
if (Test-Path $out) {
    Write-Host ("(after {0}s)" -f $elapsed)
    Get-Content -LiteralPath $out | Out-Host
} else {
    Write-Host ("no report after {0}s -- the task may not have run on an interactive desktop" -f $WaitSec) -ForegroundColor Red
    Write-Host "--- task state ---" -ForegroundColor Yellow
    schtasks /Query /TN $task /V /FO LIST 2>&1 | Select-String -Pattern "Status|Last Result|Last Run" | Out-Host
    Write-Host "--- probe console tail ($log) ---" -ForegroundColor Yellow
    if (Test-Path $log) {
        Get-Content -LiteralPath $log -Tail 40 | Out-Host
    } else {
        Write-Host "(no console log: the probe never started)" -ForegroundColor Red
    }
}
schtasks /Delete /TN $task /F | Out-Null
