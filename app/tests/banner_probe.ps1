# banner_probe.ps1 -- starts the real keyboardless.cmd the way a double-click
# does, captures its console banner for a few seconds, then kills it. Proves the
# launcher's own output (including the hotkey line read from config.json) is
# what the user actually sees, without waiting for the model to load.
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "",
    [int]    $Seconds = 8
)
$ErrorActionPreference = "Stop"
$bannerOut = Join-Path $Root "app\banner_out.txt"
$bannerErr = Join-Path $Root "app\banner_err.txt"
foreach ($f in @($bannerOut, $bannerErr)) { if (Test-Path $f) { Remove-Item -Force $f } }

$child = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", (Join-Path $Root "keyboardless.cmd")) `
    -WorkingDirectory $Root -RedirectStandardOutput $bannerOut -RedirectStandardError $bannerErr -PassThru

Start-Sleep -Seconds $Seconds
if (-not $child.HasExited) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*ar_dictate.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue
}

$lines = @()
$lines += "banner (first 14 lines of what the user sees):"
if (Test-Path $bannerOut) { $lines += (Get-Content -LiteralPath $bannerOut -Encoding UTF8 | Select-Object -First 14) }
if (Test-Path $bannerErr) {
    $e = Get-Content -LiteralPath $bannerErr -ErrorAction SilentlyContinue
    if ($e) { $lines += "--- stderr ---"; $lines += $e }
}
$report = ($lines -join "`r`n")
Write-Host $report
if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $report -Encoding UTF8 }
