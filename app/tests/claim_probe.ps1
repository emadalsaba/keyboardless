# claim_probe.ps1 -- runs claim_probe.py inside the REAL desktop session.
# SSH lands in a non-interactive window station (RegisterHotKey -> error 1459,
# "requires an interactive window station"), so the answer is only truthful when
# the probe runs on the desktop:  run_probe_interactive.ps1 -Script claim_probe.ps1
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "",
    [string[]] $Combos = @()
)

$py = Join-Path $Root ".venv\Scripts\python.exe"
$script = Join-Path $Root "app\tests\claim_probe.py"

$lines = @()
$lines += "interactive session: $([System.Environment]::UserInteractive)"
$lines += "claude.exe running: " + [bool](Get-Process -Name claude -ErrorAction SilentlyContinue)
$argList = @()
foreach ($item in $Combos) {
    $argList += @($item -split '[,\s]+' | Where-Object { $_ })
}
$lines += (& $py $script @argList 2>&1 | Out-String)

$text = ($lines -join "`r`n")
Write-Host $text
if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $text -Encoding UTF8 }
