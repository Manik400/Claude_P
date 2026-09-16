# Run the auto-apply queue every N minutes (and after every logon), silently.
#
#   powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1
#   powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1 -Every 30 -Limit 5
#   powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1 -Remove
#
# Each run refreshes the gh-pages clone, folds in what the phone asked for,
# applies to at most -Limit queued postings per board (a minute or more
# apart) and publishes the queue with every item's status back. A queue of
# many postings is finished over several runs, and the daily caps in
# Profile_Naukri_Screener-main\jobs.yaml still bound everything. Nothing appears on screen (run_hidden.vbs); output is in
# Profile_Naukri_Screener-main\logs\scheduled.log. Runs only while you are
# logged on - the headless browser needs a desktop session to fall back to.

param(
    [switch]$Remove,
    [int]$Every = 30,
    [int]$Limit = 5
)

$ErrorActionPreference = "Stop"

$root     = Split-Path -Parent $PSScriptRoot
$name     = "PhoneApplyQueue"
$batch    = Join-Path $PSScriptRoot "phone_apply.bat"
$launcher = Join-Path $root "Profile_Naukri_Screener-main\scripts\run_hidden.vbs"

foreach ($path in @($batch, $launcher)) {
    if (-not (Test-Path $path)) { throw "Cannot find $path" }
}

Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing existing task $($_.TaskName)"
        Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
    }

if ($Remove) {
    Write-Host "Phone apply queue unscheduled."
    return
}

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 50) `
    -MultipleInstances IgnoreNew

$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\wscript.exe" `
    -Argument "//B //Nologo `"$launcher`" `"$batch`" NAUKRI_APPLY_LIMIT=$Limit" `
    -WorkingDirectory $PSScriptRoot

# Repeats every -Every minutes, indefinitely, starting a few minutes from now -
# and again from two minutes after every logon, so a PC that was off when you
# tapped "add to queue" picks the request up right after it boots. Nothing is
# lost in between: the request waits on the gh-pages branch and the queue file
# remembers every item's state.
$repeat  = New-TimeSpan -Minutes $Every
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) -RepetitionInterval $repeat
$logon   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logon.Delay = "PT2M"
$logon.Repetition = $trigger.Repetition

Register-ScheduledTask `
    -TaskName $name `
    -Action $action `
    -Trigger @($trigger, $logon) `
    -Settings $settings `
    -Description "Auto-apply queue: every $Every min and after logon, up to $Limit applies per board per run." | Out-Null

Write-Host "Scheduled $name every $Every minutes (and 2 min after each logon), up to $Limit applies per board per run."
Write-Host "Check it with:   Get-ScheduledTask -TaskName '$name'"
Write-Host "Run it now with: Start-ScheduledTask -TaskName '$name'"
Write-Host "Stop it with:    ...\schedule_phone_apply.ps1 -Remove"
