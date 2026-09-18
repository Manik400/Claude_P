# Keep the Naukri profile at the top of recruiter search: refresh it every 45
# minutes, day and night, silently.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_refresh.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_refresh.ps1 -Every 30
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_refresh.ps1 -Show
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_refresh.ps1 -Remove
#
# THIS IS NOW THE PRIMARY REFRESH. jobs_scan_and_prep.bat still runs
# `main.py --refresh` as its step 2, three times a day - that is left alone on
# purpose (a scan run that also nudges the profile costs nothing extra), but it
# is no longer what keeps the timestamp fresh. This task is. The two cannot
# collide into a mess: -MultipleInstances IgnoreNew means a second
# NaukriProfileRefresh never starts while one is running, and if a scan's own
# refresh overlaps this one, the worst case is one wasted headline toggle -
# both write the same trailing full stop, and each logs its own outcome.
#
# WHAT ONE RUN DOES. refresh_profile.bat -> scripts\refresh_log.py ->
# main.py --refresh, which toggles a trailing full stop on the resume headline.
# A real edit, invisible to a human, and the whole ranking gain is the
# timestamp it bumps. It deliberately does not rotate skills or move the
# salary expectation - see jobs_scan_and_prep.bat for why.
#
# NOTHING APPEARS ON SCREEN. The task starts wscript.exe with
# scripts\run_hidden.vbs, which runs the batch with its window hidden and sets
# NAUKRI_BACKGROUND=1 so the browser is headless too. The full console output
# lands in logs\scheduled.log; the one-line-per-run summary, successes
# included, lands in logs\refresh.log and is trimmed to the last 24 hours at
# the start of every run.
#
# The task runs interactively (not "whether user is logged on or not"): if
# Naukri ever refuses the headless browser, the fallback is a headed window
# parked off-screen, and that needs a desktop session. Stay logged in to
# Windows - the lock screen is fine.

param(
    # Minutes between runs. Naukri only ranks on "when was this last modified",
    # so more often than this buys nothing; less often lets a morning's worth
    # of freshly-edited profiles get above yours.
    [int]$Every = 45,
    # Hard stop for one run, well under $Every so a hung browser can never
    # still be holding the slot when the next run is due.
    [int]$LimitMinutes = 20,
    [switch]$Remove,
    [switch]$Show
)

$ErrorActionPreference = "Stop"

$root     = Split-Path -Parent $PSScriptRoot
$name     = "NaukriProfileRefresh"
$batch    = Join-Path $root "refresh_profile.bat"
$launcher = Join-Path $PSScriptRoot "run_hidden.vbs"
$logFile  = Join-Path $root "logs\refresh.log"

function Show-State {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) { Write-Host "$name is not scheduled."; return }
    $info = $task | Get-ScheduledTaskInfo
    $rep  = ($task.Triggers | Where-Object { $_.Repetition.Interval } |
             Select-Object -First 1).Repetition.Interval
    Write-Host "${name}  state=$($task.State)  every=$rep"
    Write-Host "  last run=$($info.LastRunTime)  last result=$($info.LastTaskResult)  next run=$($info.NextRunTime)"
    Write-Host "  $($task.Description)"
    if (Test-Path $logFile) {
        Write-Host "  $logFile (last 5 lines):"
        Get-Content $logFile -Tail 5 | ForEach-Object { Write-Host "    $_" }
    } else {
        Write-Host "  $logFile does not exist yet - no run has finished."
    }
}

if ($Show) { Show-State; return }

# Re-running this script updates the schedule instead of erroring or leaving a
# stale duplicate behind.
Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing existing task $($_.TaskName)"
        Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
    }

if ($Remove) {
    Write-Host "Profile refresh unscheduled. (jobs_scan_and_prep.bat still refreshes as part of its runs.)"
    return
}

foreach ($path in @($batch, $launcher)) {
    if (-not (Test-Path $path)) { throw "Cannot find $path" }
}
if ($LimitMinutes -ge $Every) {
    throw "-LimitMinutes ($LimitMinutes) must be below -Every ($Every), or a hung run can overlap the next one."
}

# wscript.exe has no console of its own, and run_hidden.vbs starts the batch
# with its window hidden - so no cmd window, and no Chrome window either.
$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\wscript.exe" `
    -Argument "//B //Nologo `"$launcher`" `"$batch`"" `
    -WorkingDirectory $root

# THE BATTERY FLAGS ARE LOAD-BEARING ON A LAPTOP. Task Scheduler defaults
# DisallowStartIfOnBatteries and StopIfGoingOnBatteries to TRUE, and
# New-ScheduledTaskSettingsSet inherits both unless you say otherwise - which
# is how the job agent silently lost two runs a day before it set them (see
# schedule_jobs_agent.ps1). A refresh is under a minute of browsing; running it
# on battery costs nothing.
#
# IgnoreNew is what stops refreshes stacking: if one is somehow still going
# when the next 45 minutes are up, the new one is dropped, not queued.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $LimitMinutes) `
    -MultipleInstances IgnoreNew

# One trigger that starts in a minute and repeats forever, plus a logon trigger
# a few minutes after you sign in so the chain picks itself up after a reboot
# (the delay keeps it out of the way of everything else starting at logon).
#
# "Forever" has to be built by hand. The documented
# -RepetitionDuration ([TimeSpan]::MaxValue) is rejected on registration -
# it serialises to P99999999DT23H59M59S and Task Scheduler answers "value
# which is incorrectly formatted or out of range". A repetition pattern with
# an interval and NO duration is what the scheduler's own UI writes for
# "indefinitely", so build that one directly.
$first = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1)
$first.Repetition = New-CimInstance -ClientOnly `
    -Namespace "Root/Microsoft/Windows/TaskScheduler" `
    -ClassName "MSFT_TaskRepetitionPattern" `
    -Property @{ Interval = "PT${Every}M"; StopAtDurationEnd = $false }
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logon.Delay = "PT3M"

Register-ScheduledTask `
    -TaskName $name `
    -Action $action `
    -Trigger @($first, $logon) `
    -Settings $settings `
    -Description "Naukri profile refresh: bump the last-modified timestamp every $Every minutes so recruiter search keeps surfacing the profile. One line per run in logs\refresh.log, trimmed to the last 24 h." | Out-Null

Write-Host "Scheduled ${name}: first run in about a minute, then every $Every minutes, forever."
Write-Host "Each run is hidden (no console, no browser window) and stops after $LimitMinutes min at the latest."
Write-Host ""
Write-Host "State / next run:  ...\schedule_refresh.ps1 -Show"
Write-Host "                   Get-ScheduledTaskInfo -TaskName '$name'"
Write-Host "Run one now:       Start-ScheduledTask -TaskName '$name'"
Write-Host "Stop it:           ...\schedule_refresh.ps1 -Remove"
Write-Host ""
Write-Host "One line per run, successes included:  logs\refresh.log  (last 24 h only)"
Write-Host "Full console output of every run:      logs\scheduled.log"
Write-Host "If the lines start saying 'session expired', run: python main.py --login"
