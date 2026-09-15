# work_device_state.ps1 -- what is actually running / installed on the machine the
# user is testing on, right now. Read-only.
$ErrorActionPreference = 'SilentlyContinue'
$root = "C:\Users\$env:USERNAME\ar-voice-typing"

"### host: $env:COMPUTERNAME / user: $env:USERNAME / session interactive: " +
    ([bool](Get-Process explorer))

"### root folder: $root"
if (Test-Path $root) {
    Get-ChildItem $root | Select-Object Mode, LastWriteTime, Length, Name | Format-Table -AutoSize | Out-String
} else { "MISSING" }

"### ar_dictate.py copies anywhere under the root (and sizes/dates)"
Get-ChildItem -Path $root -Recurse -Filter ar_dictate.py | ForEach-Object {
    "{0}  {1} bytes  {2}" -f $_.FullName, $_.Length, $_.LastWriteTime
}

"### launcher keyboardless.cmd"
$cmdPath = Join-Path $root "keyboardless.cmd"
if (Test-Path $cmdPath) {
    $bytes = [IO.File]::ReadAllBytes($cmdPath)
    $cr = ($bytes | Where-Object { $_ -eq 13 }).Count
    $lf = ($bytes | Where-Object { $_ -eq 10 }).Count
    "path={0} len={1} CR={2} LF={3} md5={4}" -f $cmdPath, $bytes.Length, $cr, $lf,
        (Get-FileHash $cmdPath -Algorithm MD5).Hash
} else { "MISSING" }

"### python processes (name / pid / started / command line)"
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | ForEach-Object {
    "pid={0} started={1} rss={2}MB" -f $_.ProcessId, $_.CreationDate, [int]($_.WorkingSetSize/1MB)
    "    cmd: " + $_.CommandLine
    "    cwd-hint: " + $_.ExecutablePath
}

"### any ar_dictate / Keyboardless console processes"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'ar_dictate|Keyboardless' } |
    ForEach-Object { "pid=$($_.ProcessId) :: $($_.CommandLine)" }

"### dictate.log (last 25 lines)"
$log = Join-Path $root "app\dictate.log"
if (Test-Path $log) { Get-Content $log -Tail 25 -Encoding UTF8 } else { "no log at $log" }
"### root-level dictate.log"
$log2 = Join-Path $root "dictate.log"
if (Test-Path $log2) { Get-Content $log2 -Tail 10 -Encoding UTF8 } else { "no log at $log2" }

"### venv"
$py = Join-Path $root "app\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root ".venv\Scripts\python.exe" }
if (Test-Path $py) {
    "python: $py"
    "pynput: " + (& $py -c "import pynput,sys;print(pynput.__version__)" 2>&1)
    "hotkeys (read from app\config.json, with a claim check): "
    & $py (Join-Path $root "app\ar_dictate.py") --print-hotkeys 2>&1
} else { "no venv python found" }

"### scheduled tasks / probes left over"
Get-ScheduledTask -TaskName 'arDictate*' | Select-Object TaskName, State | Format-Table -AutoSize | Out-String
"done"
