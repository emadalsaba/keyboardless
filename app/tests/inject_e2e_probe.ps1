# inject_e2e_probe.ps1 -- proves that Keyboardless types Arabic text into a *focused
# text field* on Windows, not merely into a log file.
#
#   powershell -ExecutionPolicy Bypass -File inject_e2e_probe.ps1
#   powershell -ExecutionPolicy Bypass -File inject_e2e_probe.ps1 -Mode dialect -OutFile report.txt
#
# Two traps this script works around:
#   1. SendInput is denied in a non-interactive session (SSH / service), and no
#      message box can be focused there either -- so run it on a real desktop,
#      e.g. via  tests\run_probe_interactive.ps1  (scheduled task /IT).
#   2. A process started by a scheduled task may not be allowed to steal the
#      foreground, which would send the text to whatever window the user has
#      open instead of our text box. Force-Foreground() uses the
#      AttachThreadInput trick to take the foreground reliably.
#
# The child's stdout/stderr are redirected to files next to the report so a
# failed SendInput shows up as a traceback instead of a silent empty box.

param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $Wav,
    [string] $Model,
    [ValidateSet("msa", "dialect")][string] $Mode = "msa",
    [int] $TimeoutSec = 240,
    [string] $OutFile
)

$ErrorActionPreference = "Stop"

function Write-Report([string] $text) {
    if (-not $OutFile) { return }
    Set-Content -LiteralPath $OutFile -Value $text -Encoding UTF8
}
trap {
    Write-Report ("EXCEPTION: " + $_)
    Write-Host $_ -ForegroundColor Red
    exit 2
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace Probe -Name Fg -MemberDefinition @"
[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
[DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
[DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
[DllImport("user32.dll")] public static extern IntPtr SetFocus(IntPtr hWnd);
[DllImport("user32.dll")] public static extern IntPtr GetFocus();
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder text, int count);
"@

function Get-WindowText([IntPtr] $handle) {
    $sb = New-Object System.Text.StringBuilder 512
    [Probe.Fg]::GetWindowText($handle, $sb, 512) | Out-Null
    $cls = New-Object System.Text.StringBuilder 256
    [Probe.Fg]::GetClassName($handle, $cls, 256) | Out-Null
    return ("[{0}] {1}" -f $cls.ToString(), $sb.ToString())
}

function Force-Foreground([IntPtr] $handle) {
    $fgw = [Probe.Fg]::GetForegroundWindow()
    $fgPid = [uint32] 0
    $fgThread = [Probe.Fg]::GetWindowThreadProcessId($fgw, [ref] $fgPid)
    $myThread = [Probe.Fg]::GetCurrentThreadId()
    # attaching our input queue to the foreground thread lifts the
    # "background process can't take focus" restriction
    [Probe.Fg]::AttachThreadInput($myThread, $fgThread, $true) | Out-Null
    [Probe.Fg]::SetForegroundWindow($handle) | Out-Null
    [Probe.Fg]::SetFocus($handle) | Out-Null
    [Probe.Fg]::AttachThreadInput($myThread, $fgThread, $false) | Out-Null
}

$py = Join-Path $Root ".venv\Scripts\python.exe"
$script = Join-Path $Root "app\ar_dictate.py"
if (-not $Wav) { $Wav = Join-Path $Root "samples\test_msa.wav" }
if (-not $Model) { $Model = Join-Path $Root "models\vosk-model-small-ar-0.3" }
foreach ($f in @($py, $script, $Wav)) {
    if (-not (Test-Path $f)) { throw "missing: $f" }
}
$logDir = Join-Path $Root "app"
$outLog = Join-Path $logDir "probe_child_out.txt"
$errLog = Join-Path $logDir "probe_child_err.txt"

$form = New-Object System.Windows.Forms.Form
$form.Text = "Keyboardless injection probe"
$form.Width = 820
$form.Height = 220
$form.TopMost = $true
$form.StartPosition = "CenterScreen"

$tb = New-Object System.Windows.Forms.TextBox
$tb.Multiline = $true
$tb.Dock = "Fill"
$tb.ScrollBars = "Vertical"
$tb.Font = New-Object System.Drawing.Font("Segoe UI", 14)
$tb.RightToLeft = "Yes"
$tb.Text = ""
$form.Controls.Add($tb)
$form.Show()
$form.BringToFront()
[System.Windows.Forms.Application]::DoEvents()
# SetForegroundWindow only works on a TOP-LEVEL window: target the form, then
# focus its child textbox from inside our own thread.
Force-Foreground ([IntPtr] $form.Handle)
$form.Activate()
$tb.Select()
[System.Windows.Forms.Application]::DoEvents()
Start-Sleep -Milliseconds 300
[System.Windows.Forms.Application]::DoEvents()

$fgNow = [Probe.Fg]::GetForegroundWindow()
$fgIsOurs = ($fgNow -eq $form.Handle)
$fgTitle = Get-WindowText $fgNow
$focused = $tb.Focused
Write-Host ("probe window shown; foreground is ours = {0} (fg='{1}'); textbox focused = {2}; starting Keyboardless..." -f `
        $fgIsOurs, $fgTitle, $focused) -ForegroundColor Cyan

$child = Start-Process -FilePath $py -NoNewWindow -PassThru `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
    -ArgumentList @($script, "--wav", $Wav, "--injector", "sendinput", "--model", $Model, "--mode", $Mode)

$sw = [System.Diagnostics.Stopwatch]::StartNew()
while (-not $child.HasExited -and $sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
    [System.Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 40
}
$elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)
if (-not $child.HasExited) { $child.Kill(); Write-Warning "child exceeded $TimeoutSec s -- killed" }

# let queued WM_CHAR messages drain into the text box
for ($i = 0; $i -lt 30; $i++) { [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 25 }

$typed = $tb.Text
$arabic = ($typed.ToCharArray() | Where-Object { [int]$_ -ge 0x0600 -and [int]$_ -le 0x06FF }).Count
$fgAfter = [Probe.Fg]::GetForegroundWindow()
$fgAfterTitle = Get-WindowText $fgAfter
$err = if (Test-Path $errLog) { (Get-Content -LiteralPath $errLog -Raw) } else { "" }
$childOut = if (Test-Path $outLog) { (Get-Content -LiteralPath $outLog -Raw) } else { "" }

Write-Host ""
Write-Host "=== RESULT ===" -ForegroundColor Green
Write-Host ("child exit code : {0}" -f $child.ExitCode)
Write-Host ("elapsed         : {0}s" -f $elapsed)
Write-Host ("foreground ours : {0} (before) / {1} (after: {2})" -f $fgIsOurs, ($fgAfter -eq $form.Handle), $fgAfterTitle)
Write-Host ("textbox focused : {0}" -f $focused)
Write-Host ("field length    : {0} chars" -f $typed.Length)
Write-Host ("arabic chars    : {0}" -f $arabic)
Write-Host ("field content   : {0}" -f $typed)
if ($err) { Write-Host ("child stderr    : {0}" -f $err) -ForegroundColor Yellow }

Write-Report (@"
child exit code : $($child.ExitCode)
elapsed         : ${elapsed}s
foreground ours : $fgIsOurs (before) / $($fgAfter -eq $form.Handle) (after: $fgAfterTitle)
textbox focused : $focused
field length    : $($typed.Length) chars
arabic chars    : $arabic
field content   : $typed
user interactive: $([System.Environment]::UserInteractive)
child stdout    : $childOut
child stderr    : $err
"@)
$form.Close()

if ($typed.Length -gt 0 -and $arabic -gt 0) {
    Write-Host "PASS: SendInput wrote Arabic into the focused field" -ForegroundColor Green
    exit 0
}
Write-Host "FAIL: nothing (or no Arabic) reached the focused field" -ForegroundColor Red
exit 1
