# keysniff_probe.ps1 -- what does pynput actually see for an injected letter
# shortcut? Prints every key event (vk + char under the live layout) while
# sending ctrl+alt+d and ctrl+alt+space.
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = ""
)
$ErrorActionPreference = "Stop"
$app = Join-Path $Root "app"
$py = Join-Path $Root ".venv\Scripts\python.exe"
$sniffOut = Join-Path $app "sniff_out.txt"
$sniffErr = Join-Path $app "sniff_err.txt"

Add-Type -Namespace Sn -Name K -MemberDefinition @"
[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);
"@

function Send-Combo([byte[]] $keys) {
    foreach ($k in $keys) { [Sn.K]::keybd_event($k, 0, 0, [UIntPtr]::Zero) }
    Start-Sleep -Milliseconds 90
    foreach ($k in ($keys | Sort-Object -Descending)) { [Sn.K]::keybd_event($k, 0, 2, [UIntPtr]::Zero) }
    Start-Sleep -Milliseconds 200
}

foreach ($f in @($sniffOut, $sniffErr)) { if (Test-Path $f) { Remove-Item -Force $f } }

# current keyboard layout: the whole point of this probe
Add-Type -AssemblyName System.Windows.Forms
$layout = [System.Windows.Forms.InputLanguage]::CurrentInputLanguage
$layoutName = "$($layout.LayoutName) / hkl=$($layout.Handle)"

$child = Start-Process -FilePath $py -ArgumentList @("app\tests\key_sniff.py", "14") `
    -WorkingDirectory $Root -RedirectStandardOutput $sniffOut -RedirectStandardError $sniffErr -NoNewWindow -PassThru

Start-Sleep -Seconds 3
Send-Combo @(0x11, 0x12, 0x44)   # ctrl+alt+d
Start-Sleep -Seconds 2
Send-Combo @(0x11, 0x12, 0x20)   # ctrl+alt+space (worked at 16:03)
Start-Sleep -Seconds 2
$child.WaitForExit(8000) | Out-Null

$lines = @()
$lines += "keyboard layout: $layoutName"
$lines += "--- pynput saw ---"
if (Test-Path $sniffOut) { $lines += Get-Content -LiteralPath $sniffOut }
if (Test-Path $sniffErr) {
    $e = Get-Content -LiteralPath $sniffErr | Select-Object -Last 5
    if ($e) { $lines += "--- stderr ---"; $lines += $e }
}
$report = ($lines -join "`r`n")
Write-Host $report
if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $report -Encoding UTF8 }
