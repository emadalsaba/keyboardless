# win_sendinput_probe.ps1 -- proves that Keyboardless really types into a focused
# Windows text control (the SendInput path), instead of trusting the log.
#
#   powershell -NoProfile -File tests\win_sendinput_probe.ps1 -Seconds 25 -Out C:\temp\probe.txt
#
# Opens a real text box, waits, then writes whatever landed in it to -Out.
# Run this, then start the dictation with --injector sendinput in another shell.
param(
    [int]$Seconds = 25,
    [string]$Out = "$env:TEMP\Keyboardless-probe.txt"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:form = New-Object System.Windows.Forms.Form
$script:form.Text = "Keyboardless SendInput probe"
$script:form.Size = New-Object System.Drawing.Size(760, 220)
$script:form.StartPosition = "CenterScreen"
$script:form.TopMost = $true

$script:box = New-Object System.Windows.Forms.TextBox
$script:box.Multiline = $true
$script:box.Dock = "Fill"
$script:box.Font = New-Object System.Drawing.Font("Segoe UI", 14)
$script:box.AccessibleName = "probe-target"
$script:form.Controls.Add($script:box)

$script:out = $Out

$script:form.Add_Shown({
    $script:form.Activate()
    $script:box.Focus()
    $script:timer = New-Object System.Windows.Forms.Timer
    $script:timer.Interval = $Seconds * 1000
    $script:timer.Add_Tick({
        $script:timer.Stop()
        [System.IO.File]::WriteAllText($script:out, $script:box.Text,
            (New-Object System.Text.UTF8Encoding($false)))
        $script:form.Close()
    })
    $script:timer.Start()
})

[void]$script:form.ShowDialog()
