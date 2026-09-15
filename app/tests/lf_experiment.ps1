# lf_experiment.ps1 -- does cmd.exe really break on an LF-only .cmd?
# Writes two identical launchers (one LF-only, one CRLF), runs both, prints what
# each one actually executed. Evidence, not folklore.
$ErrorActionPreference = 'Continue'
$body = @(
    '@echo off',
    'if not exist "C:\Windows" (',
    '    echo BLOCK_RAN',
    ')',
    'echo AFTER_BLOCK',
    'if "%1"=="x" goto :skip',
    'echo GOTO_TARGET_REACHED',
    ':skip',
    'echo DONE'
) -join "`n"

$lf = Join-Path $env:TEMP 'lf_only.cmd'
$crlf = Join-Path $env:TEMP 'crlf_ok.cmd'
[IO.File]::WriteAllText($lf, $body + "`n", (New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText($crlf, (($body + "`n") -replace "`r?`n", "`r`n"), (New-Object Text.UTF8Encoding($false)))

foreach ($f in @($lf, $crlf)) {
    $b = [IO.File]::ReadAllBytes($f)
    $cr = ($b | Where-Object { $_ -eq 13 }).Count
    $lfCount = ($b | Where-Object { $_ -eq 10 }).Count
    "=== $f  (CR=$cr LF=$lfCount) ==="
    $out = & cmd.exe /c "`"$f`"" 2>&1 | Out-String
    if ([string]::IsNullOrWhiteSpace($out)) { "  <no output -- cmd.exe produced nothing>" } else { $out.TrimEnd() }
    "  exit code: $LASTEXITCODE"
}
