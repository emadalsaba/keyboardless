# check_probes.ps1 -- parse-check the probe scripts + list what the app folder holds.
$root = "C:\Users\$env:USERNAME\ar-voice-typing"
$files = @(
    "$root\app\tests\run_probe_interactive.ps1",
    "$root\app\tests\run_live_probe.ps1",
    "$root\app\tests\inject_e2e_probe.ps1"
)
foreach ($f in $files) {
    if (-not (Test-Path $f)) { Write-Output ("MISSING  " + $f); continue }
    $err = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$null, [ref]$err)
    if ($err -and $err.Count) {
        Write-Output ("PARSE_ERROR {0}: {1}" -f $f, $err[0].Message)
    } else {
        Write-Output ("PARSE_OK {0} ({1} bytes)" -f $f, (Get-Item $f).Length)
    }
}
Write-Output "--- app folder (recent) ---"
Get-ChildItem "$root\app" -File | Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 | ForEach-Object { "{0}  {1}" -f $_.Name, $_.Length }
