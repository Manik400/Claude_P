# Register the job agent to run several times a day via Task Scheduler.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1 -Mode apply
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1 -Remove
#
# -Mode scan   (default) finds jobs and writes the tracker page. Sends nothing.
# -Mode apply  also submits applications to the strong one-click matches.
#
# Switching mode re-registers the tasks, so you never end up with both running.
#
# The times are deliberately off the hour. Every scheduler on the planet fires
# at :00, and a run that always starts exactly at 09:00 is a more obvious
# pattern than one that starts at 08:52.
#
# The tasks run interactively (not "whether user is logged on or not") on
# purpose: both boards serve blocked pages to headless Chromium, so the agent
# needs a real desktop session to draw a browser into. A visible browser window
# will open while each run works.

param(
    # scan     search both boards, score, write the openings page. Free.
    # scanprep the same, then build that scan's Top 10 into a 100-question
    #          study page. Each run claims its own file (run 1, 2, 3), so the
    #          afternoon never overwrites the morning. Costs model tokens -
    #          roughly $5-6 for the first run of a day, less for later runs
    #          where the Top 10 has barely moved and questions carry over.
    # scanpublish scan, then push the new openings page to the phone site
    #          (jobs_scan_and_publish.bat; set up once with site\setup_phone.bat).
    # apply    submit real applications. Read jobs_agent.bat before using it.
    [ValidateSet("scan", "scanprep", "scanpublish", "apply")]
    [string]$Mode = "scan",
    [switch]$Remove,
    [string[]]$Times = @("08:52", "13:23", "18:11")
)

$ErrorActionPreference = "Stop"

$root   = Split-Path -Parent $PSScriptRoot
$prefix = "NaukriJobAgent"
$batch  = switch ($Mode) {
    "apply"    { Join-Path $root "jobs_agent.bat" }
    "scanprep" { Join-Path $root "jobs_scan_and_prep.bat" }
    "scanpublish" { Join-Path $root "jobs_scan_and_publish.bat" }
    default    { Join-Path $root "jobs_scan.bat" }
}

if (-not (Test-Path $batch)) {
    throw "Cannot find $batch"
}

# Clear any previous registration first, so re-running this script updates the
# schedule instead of erroring or leaving stale tasks behind.
Get-ScheduledTask -TaskName "$prefix*" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing existing task $($_.TaskName)"
        Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
    }

if ($Remove) {
    Write-Host "Job agent unscheduled."
    return
}

$action = New-ScheduledTaskAction -Execute $batch -WorkingDirectory $root

# THE BATTERY FLAGS ARE LOAD-BEARING ON A LAPTOP. Task Scheduler defaults
# DisallowStartIfOnBatteries and StopIfGoingOnBatteries to TRUE, and
# New-ScheduledTaskSettingsSet inherits both unless you say otherwise. On this
# machine that silently cost two of the three runs a day:
#
#   - a run due while unplugged never starts at all, and the trigger is not
#     retried - 2026-08-29 13:23 never fired, and the task's own NextRunTime
#     had already advanced to 2026-08-30
#   - a run that starts on mains and is unplugged mid-way is killed, which is
#     the 0x8007042B (ERROR_PROCESS_ABORTED) that NaukriJobAgent-2 recorded on
#     2026-08-28
#
# Both look identical from the outside: no page, no log line, no error. The
# scan is five minutes of browsing, so letting it run on battery is cheap.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

$i = 0
foreach ($time in $Times) {
    $i++
    $name = "$prefix-$i"
    $trigger = New-ScheduledTaskTrigger -Daily -At $time
    Register-ScheduledTask `
        -TaskName $name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Naukri + LinkedIn job agent ($Mode) - run $i of $($Times.Count)." | Out-Null
    Write-Host "Scheduled $name at $time  ($Mode)"
}

Write-Host ""
Write-Host "Mode: $Mode  ->  $(Split-Path -Leaf $batch)"
Write-Host "Check them with:   Get-ScheduledTask -TaskName '$prefix*'"
Write-Host "Run one now with:  Start-ScheduledTask -TaskName '$prefix-1'"
Write-Host "Stop them with:    ...\schedule_jobs_agent.ps1 -Remove"
Write-Host ""
Write-Host "Each run rewrites data\jobs\openings-<date>.html - your tracker page."
