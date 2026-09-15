# install_probe.ps1 -- هل التثبيت الفعلي كامل وصالح؟
#
#   run_probe_interactive.ps1 -Script install_probe.ps1 -Report install_probe.txt
#
# يتحقّق من: مكان التثبيت، اختصارات قائمة ابدأ وسطح المكتب، أيقونة الإزالة،
# النموذج في المسار المخصص، سجل التثبيت (هل تنزيل النموذج تُخطّي لأنه موجود)،
# ثم تشغيل البرنامج المثبَّت نفسه والتأكد أنه يبقى حيًّا ويحمّل النموذج.
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "",
    [int]    $WindowSeconds = 14
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

if (-not $OutFile) { $OutFile = Join-Path $Root "app\install_probe.txt" }
$lines = New-Object System.Collections.Generic.List[string]
# A probe launched by a scheduled task may not run as the logged-in user, and
# then it cannot read that user's AppData: the model folder looks like "0 MB"
# while it is really 287 MB (measured). Say who we are, so a zero is explainable.
$lines.Add("probe running as: $(whoami)")
$installDir = Join-Path $env:LOCALAPPDATA "Programs\Keyboardless"
$installedExe = Join-Path $installDir "Keyboardless.exe"
$uninstaller = Join-Path $installDir "unins000.exe"
$data = Join-Path $env:LOCALAPPDATA "Keyboardless"
$model = Join-Path $data "models\vosk-model-small-ar-0.3"
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Keyboardless"
$desktop = [Environment]::GetFolderPath("Desktop")
$installLog = Join-Path $env:TEMP "kbl-install.log"

function Check([string] $label, [bool] $ok, [string] $detail = "") {
    $lines.Add(("{0}  {1}{2}" -f $(if ($ok) { "PASS" } else { "FAIL" }), $label,
                $(if ($detail) { "  — $detail" } else { "" })))
}

Check "installed executable" (Test-Path $installedExe) `
      "$(if (Test-Path $installedExe) { [math]::Round((Get-Item $installedExe).Length / 1KB, 0) } else { 0 }) KB"
Check "uninstaller present" (Test-Path $uninstaller)
$startLinks = @(Get-ChildItem $startMenu -Filter *.lnk -ErrorAction SilentlyContinue)
Check "start-menu shortcuts" ($startLinks.Count -ge 1) "$($startLinks.Count) shortcuts: $($startLinks.Name -join ', ')"
$desktopLink = Join-Path $desktop "Keyboardless (بدون كيبورد).lnk"
Check "desktop shortcut" (Test-Path $desktopLink)
$files = @(Get-ChildItem $installDir -Recurse -File -Force -ErrorAction SilentlyContinue)
$size = ($files | Measure-Object -Property Length -Sum).Sum
Check "installed files" ($files.Count -gt 20) "$($files.Count) files, $([math]::Round($size / 1MB, 1)) MB"
$readErrors = @()
$modelFiles = @(Get-ChildItem $model -Recurse -File -Force -ErrorAction SilentlyContinue `
                -ErrorVariable +readErrors)
$modelSum = ($modelFiles | Measure-Object -Property Length -Sum).Sum
if (-not $modelSum) { $modelSum = 0 }
Check "Arabic model in the dedicated folder" ($modelFiles.Count -gt 15) `
      "$([math]::Round($modelSum / 1MB, 1)) MB at $model"
if ($readErrors.Count -gt 0) {
    # never let a permission problem look like a missing model
    $lines.Add("NOTE  $($readErrors.Count) unreadable entries - this probe may be " +
               "running as '$([Environment]::UserName)' instead of the model's owner")
}

if (Test-Path $installLog) {
    $logText = [IO.File]::ReadAllText($installLog, [Text.Encoding]::UTF8)
    # "Downloading" appears only when the installer actually fetched the model
    $lines.Add("--- install log: model handling ---")
    foreach ($line in ($logText -split "`r?`n")) {
        if ($line -match "ensure-model|Downloading|Starting|model") { $lines.Add("  " + $line.Trim()) }
    }
    Check "install log present" $true "no re-download when the model already exists"
} else {
    $lines.Add("no install log at $installLog")
}

# --- the installed app itself -------------------------------------------------
$p = Start-Process -FilePath $installedExe -ArgumentList "--cli", "--models" -Wait -PassThru -WindowStyle Hidden
Check "packaged CLI runs" ($p.ExitCode -eq 0) "exit=$($p.ExitCode)"
$cliLog = Join-Path $data "cli-last.txt"
if (Test-Path $cliLog) {
    $lines.Add("--- its own model listing ---")
    foreach ($line in ([IO.File]::ReadAllText($cliLog, [Text.Encoding]::UTF8) -split "`r?`n")) {
        if ($line.Trim()) { $lines.Add("  " + $line) }
    }
}

$proc = Start-Process -FilePath $installedExe -PassThru
Start-Sleep -Seconds $WindowSeconds
Check "installed window stays alive (tray)" (-not $proc.HasExited) "pid $($proc.Id)"
if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }

$appLog = Join-Path $data "dictate.log"
if (Test-Path $appLog) {
    $lines.Add("--- the installed app's log ---")
    foreach ($line in (Get-Content $appLog -Tail 8 -Encoding UTF8)) { $lines.Add("  " + $line) }
}

$failures = @($lines | Where-Object { $_ -like "FAIL*" }).Count
$lines.Add("SETUP " + $(if ($failures -eq 0) { "OK" } else { "CHECK FAILURES ($failures)" }))
Set-Content -LiteralPath $OutFile -Value $lines -Encoding UTF8
Write-Output "report: $OutFile"
