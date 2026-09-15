# quiet_agc_probe.ps1 -- "the hotkey works but nothing is typed", proven fixed
# on the machine itself.
#
# Builds a copy of the known-good Arabic sample at the level this laptop's
# microphone actually delivers (peak 0.004) and dictates it twice: once with the
# auto-gain off (the old behaviour: silence) and once with it on (the fix). Runs
# from a plain SSH session -- no desktop needed, nothing is typed anywhere.
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "quiet_agc.txt",
    [double] $Peak = 0.004
)

$ErrorActionPreference = "Continue"
chcp 65001 > $null
$env:PYTHONIOENCODING = "utf-8"
# Python writes UTF-8; without this, PowerShell decodes its output as the legacy
# code page and Arabic arrives as mojibake (which silently counts as zero)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
$quiet = "samples\quiet_$($Peak.ToString('0.000').Replace('.','')).wav"

$report = @()
$report += "python: " + (& $py --version)
$report += "quiet sample: $quiet (peak $Peak)"

$build = & $py "app\tests\attenuate.py" "samples\test_msa.wav" "$Peak" $quiet *>&1
$report += $build

function ArabicLength([string] $text) {
    # count code points rather than trust a regex escape in PowerShell strings
    $count = 0
    foreach ($ch in $text.ToCharArray()) {
        $code = [int] $ch
        if ($code -ge 0x0600 -and $code -le 0x06FF) { $count++ }
    }
    return $count
}

foreach ($mode in @("off", "on")) {
    $out = (& $py "app\ar_dictate.py" "--wav" $quiet "--injector" "stdout" "--agc" $mode *>&1) -join "`n"
    # the injector writes bare text; log lines are timestamped
    $typed = ($out -split "`n" | ForEach-Object { $_ -replace "\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.*$", "" }) -join " "
    $chars = ArabicLength $typed
    $report += "agc=$mode -> arabic chars typed: $chars"
    if ($mode -eq "on") {
        $sample = ($typed -replace "\s+", " ").Trim()
        if ($sample.Length -gt 160) { $sample = $sample.Substring(0, 160) }
        $report += "agc=on text: $sample"
        $rtf = ($out -split "`n" | Where-Object { $_ -match "RTF=" })
        $report += "agc=on timing: $rtf"
    }
}

$verdict = if ((ArabicLength $typed) -gt 20) { "VERDICT: auto-gain fixes the quiet microphone on this machine" }
           else { "VERDICT: STILL BROKEN -- investigate further" }
$report += $verdict
Set-Content -LiteralPath $OutFile -Value $report -Encoding UTF8
$report | ForEach-Object { Write-Output $_ }
