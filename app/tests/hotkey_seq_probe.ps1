# hotkey_seq_probe.ps1 -- presses EVERY configured hotkey in order and reports
# which action the app actually performed (from its own log), then whether the
# quit key ended the process. This is the honest answer to "the shortcut does
# nothing": either the key never reaches the app, or it reaches it and the
# action is missing. Run it on the real desktop:
#   run_probe_interactive.ps1 -Script hotkey_seq_probe.ps1 -Report hotkey_seq.txt
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "",
    [int]    $ReadySec = 90
)

$ErrorActionPreference = "Stop"
$app = Join-Path $Root "app"
$py = Join-Path $Root ".venv\Scripts\python.exe"
$outLog = Join-Path $app "seq_out.txt"
$errLog = Join-Path $app "seq_err.txt"
$log = Join-Path $app "dictate.log"

Add-Type -Namespace Seq -Name K -MemberDefinition @"
[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);
"@

function Get-ComboKeys([string] $spec) {
    $map = @{ ctrl = 0x11; control = 0x11; alt = 0x12; shift = 0x10; win = 0x5B
              cmd = 0x5B; super = 0x5B; space = 0x20; tab = 0x09; enter = 0x0D }
    $out = New-Object System.Collections.Generic.List[byte]
    foreach ($part in ($spec -split '\+')) {
        $p = $part.Trim().ToLower()
        if ($p -match '^[a-z]$') { $out.Add([byte][char]$p.ToUpper()) }
        elseif ($p -match '^[0-9]$') { $out.Add([byte][char]$p) }
        elseif ($p -match '^f([1-9]|1[0-2])$') { $out.Add([byte](0x6F + [int]$Matches[1])) }
        elseif ($map.ContainsKey($p)) { $out.Add([byte]$map[$p]) }
        else { throw "unknown key '$p' in '$spec'" }
    }
    return [byte[]]$out
}

function Send-Combo([string] $spec) {
    $keys = Get-ComboKeys $spec
    foreach ($k in $keys) { [Seq.K]::keybd_event($k, 0, 0, [UIntPtr]::Zero) }
    Start-Sleep -Milliseconds 90
    foreach ($k in ($keys | Sort-Object -Descending)) { [Seq.K]::keybd_event($k, 0, 2, [UIntPtr]::Zero) }
    Start-Sleep -Milliseconds 150
}

$cfg = Get-Content -LiteralPath (Join-Path $app "config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$combos = @($cfg.hotkey)
$startKey = $combos[0]
$stopKey = if ($combos.Count -gt 1) { $combos[1] } else { $combos[0] }
$modeKey = $cfg.mode_key
$quitKey = $cfg.quit_key

foreach ($f in @($outLog, $errLog, $log)) {
    if (Test-Path $f) { Remove-Item -Force $f }
}

$lines = @()
$lines += "start=$startKey  stop=$stopKey  mode=$modeKey  quit=$quitKey"
$child = Start-Process -FilePath $py `
    -ArgumentList @("ar_dictate.py", "--profile", "fast", "--verbose") `
    -WorkingDirectory $app -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
    -NoNewWindow -PassThru

$deadline = (Get-Date).AddSeconds($ReadySec)
$ready = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    if ($child.HasExited) { break }
    $tail = ""
    if (Test-Path $outLog) { $tail += (Get-Content -LiteralPath $outLog -Raw) }
    if (Test-Path $log) { $tail += (Get-Content -LiteralPath $log -Raw) }
    if ($tail -match "Keyboardless ready") { $ready = $true; break }
}
$lines += "engine ready        : $ready"

Send-Combo $startKey
Start-Sleep -Seconds 5
Send-Combo $stopKey
Start-Sleep -Seconds 3
Send-Combo $modeKey
Start-Sleep -Seconds 3
Send-Combo $quitKey
Start-Sleep -Seconds 6

$exited = $child.HasExited
$text = ""
if (Test-Path $outLog) { $text += (Get-Content -LiteralPath $outLog -Raw) }
if (Test-Path $log) { $text += (Get-Content -LiteralPath $log -Raw) }

$lines += "start key acted     : " + ($text -match "dictation START")
$lines += "stop key acted      : " + ($text -match "dictation STOP")
$lines += "mode key acted      : " + ($text -match "mode switched")
$lines += "quit key exited app : $exited"

if (-not $exited) { Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue }
if (Test-Path $log) {
    $lines += "--- dictate.log ---"
    $lines += (Get-Content -LiteralPath $log | Select-Object -Last 12)
}
if (Test-Path $errLog) {
    $tailErr = (Get-Content -LiteralPath $errLog | Select-Object -Last 6)
    if ($tailErr) { $lines += "--- stderr ---"; $lines += $tailErr }
}

$report = ($lines -join "`r`n")
Write-Host $report
if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $report -Encoding UTF8 }
