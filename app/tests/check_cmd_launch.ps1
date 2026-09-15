# check_cmd_launch.ps1 -- does the double-click launcher (keyboardless.cmd) really
# start ar_dictate.py, and WHERE does its log land? Run over a plain SSH session
# (non-interactive) -- the mic/model load does not need a desktop, only SendInput does.
$root = "C:\Users\$env:USERNAME\ar-voice-typing"
$log  = Join-Path $root "app\dictate.log"
$rootLog = Join-Path $root "dictate.log"

Write-Output "--- cleanup ---"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*ar_dictate*" } |
    ForEach-Object { Write-Output ("kill stray pid " + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }
Remove-Item $log, $rootLog -Force -ErrorAction SilentlyContinue

Write-Output "--- launching exactly like a double-click ---"
$p = Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", (Join-Path $root "keyboardless.cmd")) `
    -WorkingDirectory $root -PassThru
Write-Output ("cmd pid {0}" -f $p.Id)

$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt 60) {
    Start-Sleep -Seconds 5
    $py = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*ar_dictate*" })
    if ($rootLog -and (Test-Path $rootLog)) { break }
    if ($log -and (Test-Path $log)) { break }
}
Write-Output ("cmd alive: {0}; waited {1}s" -f (-not $p.HasExited), [int]$sw.Elapsed.TotalSeconds)

Write-Output "--- python processes ---"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    ForEach-Object {
        $cl = $_.CommandLine; if ($cl.Length -gt 120) { $cl = $cl.Substring(0, 120) }
        Write-Output ("pid {0} :: {1}" -f $_.ProcessId, $cl)
    }

Write-Output "--- dictate.log hunt ---"
Get-ChildItem $root -Recurse -Depth 2 -Filter "dictate.log" -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Output ("FOUND " + $_.FullName + " (" + $_.Length + " bytes)"); Get-Content $_.FullName -Tail 6 | ForEach-Object { "    " + $_ } }

Write-Output "--- app\ (recent 6) ---"
Get-ChildItem (Join-Path $root "app") -File | Sort-Object LastWriteTime -Descending |
    Select-Object -First 6 | ForEach-Object { "{0}  {1}" -f $_.Name, $_.Length }

Write-Output "--- cleanup ---"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*ar_dictate*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Write-Output "done"
