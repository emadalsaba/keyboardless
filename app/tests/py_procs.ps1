# py_procs.ps1 -- every python.exe on this machine, with its start time and
# command line. Stale ar_dictate instances keep a global keyboard hook and can
# swallow the hotkey of the app you think you just started, so this must be
# checked whenever a shortcut "does nothing".
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CreationDate, ParentProcessId,
        @{ n = 'cmd'; e = {
            if ($_.CommandLine) { $_.CommandLine.Substring(0, [Math]::Min(110, $_.CommandLine.Length)) }
            else { '(none)' }
        } } |
    Sort-Object CreationDate |
    Format-Table -AutoSize | Out-String -Width 220
