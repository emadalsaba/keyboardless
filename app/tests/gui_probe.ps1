# gui_probe.ps1 -- run the settings window's self-test inside the real desktop
# session (that is where a system tray actually exists) and report the result.
#
#   run_probe_interactive.ps1 -Script gui_probe.ps1 -Report gui_selftest.txt
#
# The window is driven on a *copy* of config.json and writes its dictated text to
# stdout, so nothing is typed into whatever the user has open and no setting is
# changed behind their back.
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "gui_selftest.txt",
    [int]    $ModelWait = 120,
    [switch] $Offscreen,     # run without a desktop session (over SSH) - no tray
    [switch] $ShotOnly,      # just render the window to a PNG and exit
    [switch] $ShotAbout,     # render only the About box
    [int]    $Tab = 0        # which tab the -ShotOnly render shows
)

$ErrorActionPreference = "Continue"
# Without this the Arabic the window prints comes back as mojibake and every
# count of it reads as zero (a false "broken" verdict).
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$lines = New-Object System.Collections.Generic.List[string]
$py = Join-Path $Root ".venv\Scripts\python.exe"
$shot = Join-Path $Root "app\gui_shot.png"
Push-Location $Root

$extra = @()
if ($Offscreen) {
    $env:QT_QPA_PLATFORM = "offscreen"
    $extra = @("--no-tray")
    $lines.Add("platform: offscreen (no tray, usable over SSH)")
}

$lines.Add("root: $Root")
$lines.Add("python: $py (exists: $(Test-Path $py))")
if ($ShotAbout) {
    $out = & $py "app\gui.py" --shot-about (Join-Path $Root "app\about_shot.png") @extra 2>&1
} elseif ($ShotOnly) {
    # renders with the real desktop fonts, which is what the user will see
    $out = & $py "app\gui.py" --shot $shot --shot-tab $Tab @extra 2>&1
} else {
    $out = & $py "app\gui.py" --selftest --shot $shot --model-wait $ModelWait @extra 2>&1
}
$code = $LASTEXITCODE
Pop-Location

foreach ($line in $out) { $lines.Add([string] $line) }
$lines.Add("exit code: $code")
$lines.Add("screenshot exists: $(Test-Path $shot)")
if (Test-Path $shot) { $lines.Add("screenshot bytes: " + (Get-Item $shot).Length) }

Set-Content -LiteralPath $OutFile -Value $lines -Encoding UTF8
