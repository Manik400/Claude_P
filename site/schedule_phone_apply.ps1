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
    [int]$Limit = 0,         # applies per board per run; 0 = every queued posting the run has time for (daily caps still hold)
    [int]$Minutes = 100      # a run keeps applying for this long (APPLY_MAX_MINUTES); the task is stopped at +20
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
    -WakeToRun `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes ($Minutes + 20)) `
    -MultipleInstances IgnoreNew

# JOBGUARD_MAX_MINUTES: the wall-clock hard stop (scripts\jobguard.py) - Task
# Scheduler's own limit stands still while the laptop sleeps.
$argument = "//B //Nologo `"$launcher`" `"$batch`" APPLY_MAX_MINUTES=$Minutes JOBGUARD_MAX_MINUTES=$($Minutes + 20)"
if ($Limit -gt 0) { $argument += " NAUKRI_APPLY_LIMIT=$Limit" }
$capText = if ($Limit -gt 0) { "up to $Limit applies per board per run" } else { "every queued posting a run has time for" }
$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\wscript.exe" `
    -Argument $argument `
    -WorkingDirectory $PSScriptRoot

# Repeats every -Every minutes, indefinitely, starting a few minutes from now -
# and again from two minutes after every logon, so a PC that was off when you
# tapped "add to queue" picks the request up right after it boots. Nothing is
# lost in between: the request waits on the gh-pages branch and the queue file
# remembers every item's state.
$repeat  = New-TimeSpan -Minutes $Every
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) -RepetitionInterval $repeat
$logon   = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT2M"
# One run after logon, no repetition of its own: a repeating logon trigger ran a
# second 30-minute chain beside the first (runs at :01 :20 :31 :50 - twice as
# many as asked for).

Register-ScheduledTask `
    -TaskName $name `
    -Action $action `
    -Trigger @($trigger, $logon) `
    -Settings $settings `
    -Description "Auto-apply queue: every $Every min and after logon, $capText." | Out-Null

Write-Host "Scheduled $name every $Every minutes (and 2 min after each logon), $capText."
Write-Host "Check it with:   Get-ScheduledTask -TaskName '$name'"
Write-Host "Run it now with: Start-ScheduledTask -TaskName '$name'"
Write-Host "Stop it with:    ...\schedule_phone_apply.ps1 -Remove"
