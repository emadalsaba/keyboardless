# mic_probe.ps1 -- "the hotkey works but nothing is typed": is audio reaching
# the app at all? Records from the configured input device in the REAL desktop
# session and reports the level, the transcript, and the window that is focused.
# Contract: called by run_probe_interactive.ps1 (-Root / -OutFile).
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "mic_result.txt",
    [int]    $Secs = 6
)
chcp 65001 > $null
$env:PYTHONIOENCODING = "utf-8"
# Python writes UTF-8; the legacy code page would turn Arabic into mojibake
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$lines = New-Object System.Collections.Generic.List[string]
Add-Type -Namespace W -Name Win -MemberDefinition @'
[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
'@
$h = [W.Win]::GetForegroundWindow()
$sb = New-Object System.Text.StringBuilder 512
[void][W.Win]::GetWindowText($h, $sb, 512)
$lines.Add("foreground window now: " + $sb.ToString())

$py = Join-Path $Root ".venv\Scripts\python.exe"
Push-Location $Root
$out = & $py "app\ar_dictate.py" --mic-level $Secs 2>&1
$code = $LASTEXITCODE
Pop-Location
foreach ($l in $out) { $lines.Add([string]$l) }
$lines.Add("mic-level exit code: $code")

$dst = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path $Root "app\$OutFile" }
Set-Content -LiteralPath $dst -Value $lines -Encoding UTF8
Write-Host ("wrote " + $dst)
