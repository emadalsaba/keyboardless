# who_is_here.ps1 -- is the Hermes desktop app running on this machine?
Get-Process | Where-Object { $_.ProcessName -match 'hermes|electron|node' } |
    Select-Object ProcessName, Id, StartTime | Format-Table -AutoSize | Out-String -Width 120
"python processes: {0}" -f (Get-Process python* -ErrorAction SilentlyContinue).Count
"--- listening ports 9224/5000/8080 ---"
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 9224, 5000, 8080, 3000 } |
    Select-Object LocalPort, OwningProcess | Format-Table -AutoSize | Out-String -Width 80
