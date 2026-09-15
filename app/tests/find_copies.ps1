# find_copies.ps1 -- every copy of the dictation app on this machine.
# A stale copy (Desktop/Downloads/another folder) explains "double-click did
# nothing": it still has the LF launcher / old model paths.
$ErrorActionPreference = 'SilentlyContinue'
$home_ = $env:USERPROFILE
"USERPROFILE: $home_"
"--- folders matching ar-voice-typing / ar_dictate ---"
Get-ChildItem -Path $home_ -Directory -Recurse -Depth 4 -Filter 'ar-voice-typing*' |
    Select-Object -ExpandProperty FullName
"--- launchers anywhere under the profile ---"
Get-ChildItem -Path $home_ -File -Recurse -Depth 5 -Include 'keyboardless*.cmd', 'ar-dictate*.cmd' |
    ForEach-Object {
        $b = [IO.File]::ReadAllBytes($_.FullName)
        $cr = ($b | Where-Object { $_ -eq 13 }).Count
        $lf = ($b | Where-Object { $_ -eq 10 }).Count
        "{0}|{1}|bytes={2}|CR={3}|LF={4}|mtime={5}" -f $_.FullName, (Get-FileHash $_.FullName -Algorithm MD5).Hash, $b.Length, $cr, $lf, $_.LastWriteTime
    }
"--- ar_dictate.py copies ---"
Get-ChildItem -Path $home_ -File -Recurse -Depth 5 -Include 'ar_dictate.py' |
    ForEach-Object { "{0}|bytes={1}|mtime={2}" -f $_.FullName, $_.Length, $_.LastWriteTime }
"--- zip/archives containing ar-voice-typing ---"
Get-ChildItem -Path $home_ -File -Recurse -Depth 4 -Include '*.zip', '*.tar.gz' |
    Where-Object { $_.Name -match 'voice|dictate|ar-' } | Select-Object -ExpandProperty FullName
