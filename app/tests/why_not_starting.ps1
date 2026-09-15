# why_not_starting.ps1 -- capture what the launcher itself prints, so a silent
# exit is no longer invisible. Reads the .cmd's stdout+stderr and the venv state.
$root = "C:\Users\$env:USERNAME\ar-voice-typing"
$cmd  = Join-Path $root "keyboardless.cmd"
$out  = Join-Path $root "app\cmdout.txt"

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*ar_dictate*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item $out -Force -ErrorAction SilentlyContinue

Write-Output ("--- launcher bytes ---")
$b = [IO.File]::ReadAllBytes($cmd)
Write-Output ("len={0} crlf={1} loneLF={2}" -f $b.Length, ($b -join ',' | Select-String -AllMatches -Pattern '13,10').Matches.Count, 0)

Write-Output "--- python.exe candidates ---"
Write-Output ("venv python exists: " + (Test-Path (Join-Path $root ".venv\Scripts\python.exe")))
Get-Command python, py -ErrorAction SilentlyContinue | ForEach-Object { "on PATH: " + $_.Source }

Write-Output "--- running the .cmd with output captured ---"
$p = Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", "$cmd > `"$out`" 2>&1") `
    -WorkingDirectory $root -PassThru
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt 45) {
    Start-Sleep -Seconds 3
    if (Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*ar_dictate*" }) { break }
}
Write-Output ("cmd alive: {0} after {1}s" -f (-not $p.HasExited), [int]$sw.Elapsed.TotalSeconds)

Write-Output "--- launcher output (cmdout.txt) ---"
if (Test-Path $out) {
    Get-Content $out -Encoding Default | ForEach-Object { "  |  " + $_ }
} else {
    Write-Output "  (no cmdout.txt -- redirection never happened)"
}

Write-Output "--- dictate.log (anywhere under root) ---"
Get-ChildItem $root -Recurse -Depth 2 -Filter "dictate.log" -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Output ("FOUND " + $_.FullName + " (" + $_.Length + "b)"); Get-Content $_.FullName -Tail 4 | ForEach-Object { "  |  " + $_ } }

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*ar_dictate*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Write-Output "done"
