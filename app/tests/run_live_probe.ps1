# run_live_probe.ps1 -- verifies the LIVE dictation path (mic + global hotkey)
# without needing anyone to speak: starts Keyboardless, injects the configured
# dictate combination read from app\config.json (a hardcoded key here once kept
# "passing" while the real shortcut was owned by another program), and checks
# that the app actually opened the microphone and started streaming.
# Must run in the real desktop session (see run_probe_interactive.ps1).

param(
    [string] $Root = (Join-Path $env:USERPROFILE "ar-voice-typing"),
    [int]    $ReadySec = 90,
    [int]    $ListenSec = 8,
    [string] $OutFile = "",
    [string] $Dictate = "",   # override; default = first hotkey in config.json
    [ValidateSet("python", "cmd")][string] $Launcher = "python"
)

$ErrorActionPreference = "Stop"
$app = Join-Path $Root "app"
$py = Join-Path $Root ".venv\Scripts\python.exe"
$outLog = Join-Path $app "live_out.txt"
$errLog = Join-Path $app "live_err.txt"
$log = Join-Path $app "dictate.log"

Add-Type -Namespace Live -Name K -MemberDefinition @"
[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);
"@

function Send-Combo([byte[]] $keys) {
    foreach ($k in $keys) { [Live.K]::keybd_event($k, 0, 0, [UIntPtr]::Zero) }
    Start-Sleep -Milliseconds 80
    foreach ($k in ($keys | Sort-Object -Descending)) { [Live.K]::keybd_event($k, 0, 2, [UIntPtr]::Zero) }
    Start-Sleep -Milliseconds 150
}

$cfgPath = Join-Path $app "config.json"
$cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Dictate) { $Dictate = @($cfg.hotkey)[0] }
$ModeKey = $cfg.mode_key
$QuitKey = $cfg.quit_key

function Get-ComboKeys([string] $spec) {
    # translate the config form (ctrl+alt+d / ctrl+alt+j) into virtual keys
    $map = @{ ctrl = 0x11; control = 0x11; alt = 0x12; shift = 0x10; win = 0x5B
              cmd = 0x5B; super = 0x5B; space = 0x20; tab = 0x09; enter = 0x0D }
    $out = New-Object System.Collections.Generic.List[byte]
    foreach ($part in ($spec -split '\+')) {
        $p = $part.Trim().ToLower()
        if ($p -match '^[a-z]$') { $out.Add([byte][char]$p.ToUpper()) }
        elseif ($p -match '^[0-9]$') { $out.Add([byte][char]$p) }
        elseif ($p -match '^f([1-9]|1[0-2])$') { $out.Add([byte](0x6F + [int]$Matches[1])) }
        elseif ($map.ContainsKey($p)) { $out.Add([byte]$map[$p]) }
        else { throw "unknown key '$p' in combination '$spec'" }
    }
    return [byte[]]$out
}

if (Test-Path $outLog) { Remove-Item -Force $outLog }
if (Test-Path $errLog) { Remove-Item -Force $errLog }
if (Test-Path $log)    { Remove-Item -Force $log }

Write-Host "starting Keyboardless (live mic mode) ..." -ForegroundColor Cyan
if ($Launcher -eq "cmd") {
    # exactly what a double-click on keyboardless.cmd does
    $child = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", (Join-Path $Root "keyboardless.cmd")) `
        -WorkingDirectory $Root -PassThru
} else {
    $child = Start-Process -FilePath $py `
        -ArgumentList @("ar_dictate.py", "--profile", "fast", "--verbose") `
        -WorkingDirectory $app -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
        -NoNewWindow -PassThru
}

$deadline = (Get-Date).AddSeconds($ReadySec)
$ready = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    if ($child.HasExited) { break }
    $tail = ""
    if (Test-Path $outLog) { $tail += (Get-Content -LiteralPath $outLog -Raw) }
    if (Test-Path $log)    { $tail += (Get-Content -LiteralPath $log -Raw) }
    if ($tail -match "hotkeys|ready") { $ready = $true; break }
}
Write-Host ("engine ready: {0} (pid {1}, exited={2})" -f $ready, $child.Id, $child.HasExited)

# prefer a second configured combination for the stop press: it proves the
# fallback key is captured too, not just the first one.
$startCombo = $Dictate
$stopCombo = $Dictate
if ((-not $PSBoundParameters.ContainsKey("Dictate")) -and @($cfg.hotkey).Count -gt 1) {
    $stopCombo = @($cfg.hotkey)[1]
}

Write-Host ("sending {0} (start dictation) ..." -f $startCombo) -ForegroundColor Cyan
Send-Combo (Get-ComboKeys $startCombo)
$listenOk = $false
$t2 = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $t2) {
    Start-Sleep -Milliseconds 400
    if ($child.HasExited) { break }
    if ((Test-Path $log) -and ((Get-Content -LiteralPath $log -Raw) -match "listening on device")) { $listenOk = $true; break }
}
$listenColor = "Red"
if ($listenOk) { $listenColor = "Green" }
Write-Host ("microphone opened + streaming: {0}" -f $listenOk) -ForegroundColor $listenColor

Start-Sleep -Seconds $ListenSec
Write-Host ("sending {0} (stop) ..." -f $stopCombo)
Send-Combo (Get-ComboKeys $stopCombo)
Start-Sleep -Seconds 2

Write-Host ("sending {0} (switch dialect mode) ..." -f $ModeKey)
Send-Combo (Get-ComboKeys $ModeKey)
Start-Sleep -Seconds 2

Write-Host ("sending {0} (quit) ..." -f $QuitKey)
Send-Combo (Get-ComboKeys $QuitKey)
Start-Sleep -Seconds 3

$exitedOnHotkey = $false
$exitCode = "n/a"
if ($Launcher -eq "cmd") {
    # the .cmd wrapper pauses after python exits, so judge the python child
    $still = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*ar_dictate.py*" })
    $exitedOnHotkey = ($still.Count -eq 0)
    if (-not $exitedOnHotkey) { Write-Host "python still alive; killing tree." -ForegroundColor Yellow }
    # taskkill writes to stderr when the pid is already gone, and with
    # $ErrorActionPreference = "Stop" that aborts the probe *after* the run has
    # already succeeded -- the report file never got written (seen on desktop).
    # The app exiting on the quit hotkey is the desired outcome, so a dead pid
    # here is not an error.
    cmd /c "taskkill /PID $($child.Id) /T /F >nul 2>&1" | Out-Null
} else {
    if (-not $child.HasExited) { Write-Host "app did not exit on hotkey; killing." -ForegroundColor Yellow; $child.Kill() }
    $child.Refresh()
    $exitedOnHotkey = $child.HasExited
    $exitCode = $child.ExitCode
}

$child.Refresh()
$logTail = if (Test-Path $log) { (Get-Content -LiteralPath $log -Tail 25) -join "`n" } else { "(no log)" }
$out = if (Test-Path $outLog) { Get-Content -LiteralPath $outLog -Raw } else { "" }
$err = if (Test-Path $errLog) { Get-Content -LiteralPath $errLog -Raw } else { "" }

Write-Host ""
Write-Host "=== LIVE PROBE RESULT ===" -ForegroundColor Green
Write-Host ("engine ready        : {0}" -f $ready)
Write-Host ("mic opened/streaming: {0}" -f $listenOk)
Write-Host ("exited on hotkey    : {0} (exit {1})" -f $exitedOnHotkey, $exitCode)
Write-Host ""
Write-Host "--- dictate.log (tail) ---"
Write-Host $logTail
if ($err) { Write-Host "--- stderr ---"; Write-Host $err -ForegroundColor Yellow }

if ($OutFile) {
    $report = @"
engine ready        : $ready
mic opened/streaming: $listenOk
exited on hotkey    : $exitedOnHotkey (exit $exitCode)
stdout              : $out
stderr              : $err
--- dictate.log (tail) ---
$logTail
"@
    Set-Content -LiteralPath $OutFile -Value $report -Encoding UTF8
}
