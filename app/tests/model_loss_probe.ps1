# model_loss_probe.ps1 -- من يحذف النموذج بعد التثبيت؟
#
#   powershell -ExecutionPolicy Bypass -File app\tests\model_loss_probe.ps1
#
# الخطوات: (١) حالة المجلد الآن، (٢) تنزيل نظيف عبر تطبيق المثبَّت، (٣) قياس الحجم
# قبل تشغيل النافذة وبعدها، (٤) ترك النافذة ٢٥ ثانية ثم قياس الحجم مرة أخرى —
# فإن نزل الحجم إلى الصفر فالحاذف هو التطبيق نفسه، وإن بقي فالحاذف غيره.
param(
    [string] $Root = "C:\Users\$env:USERNAME\ar-voice-typing",
    [string] $OutFile = "",
    [int]    $WindowSeconds = 25
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

if (-not $OutFile) { $OutFile = Join-Path $Root "app\model_loss_probe.txt" }
$lines = New-Object System.Collections.Generic.List[string]
$data = Join-Path $env:LOCALAPPDATA "Keyboardless"
$models = Join-Path $data "models"
$exe = Join-Path $env:LOCALAPPDATA "Programs\Keyboardless\Keyboardless.exe"
if (-not (Test-Path $exe)) { $exe = Join-Path $Root "dist\Keyboardless\Keyboardless.exe" }

function Size-Of([string] $path, [string] $label) {
    if (-not (Test-Path $path)) { $script:last = "MISSING"; $lines.Add("$label : MISSING"); return }
    $files = @(Get-ChildItem $path -Recurse -File -Force -ErrorAction SilentlyContinue)
    $sum = ($files | Measure-Object -Property Length -Sum).Sum
    if (-not $sum) { $sum = 0 }
    $script:last = "$([math]::Round($sum / 1MB, 1)) MB / $($files.Count) files"
    $lines.Add("$label : $($script:last)")
}

$lines.Add("exe: $exe")
$lines.Add("models dir: $models")
Size-Of (Join-Path $models "vosk-model-small-ar-0.3") "1. now"

$lines.Add("")
$lines.Add("2. تنزيل نظيف عبر التطبيق المثبَّت (--cli --ensure-model) …")
$p = Start-Process -FilePath $exe -ArgumentList "--cli", "--ensure-model" -Wait -PassThru -WindowStyle Hidden
$lines.Add("   exit=$($p.ExitCode)")
Size-Of (Join-Path $models "vosk-model-small-ar-0.3") "   after download"

$lines.Add("")
$lines.Add("3. تشغيل النافذة المثبَّتة $WindowSeconds ثانية …")
$proc = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 6
Size-Of (Join-Path $models "vosk-model-small-ar-0.3") "   +6s (model loading)"
Start-Sleep -Seconds ($WindowSeconds - 6)
Size-Of (Join-Path $models "vosk-model-small-ar-0.3") "   +${WindowSeconds}s"
$alive = -not $proc.HasExited
$lines.Add("   window alive: $alive")
if ($alive) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }

$log = Join-Path $data "dictate.log"
if (Test-Path $log) {
    $lines.Add("")
    $lines.Add("--- app log (tail) ---")
    foreach ($line in (Get-Content $log -Tail 10 -Encoding UTF8)) { $lines.Add("  " + $line) }
}

Set-Content -LiteralPath $OutFile -Value $lines -Encoding UTF8
Write-Output "report: $OutFile"
