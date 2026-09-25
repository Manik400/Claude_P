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
# HOW MANY IT APPLIES TO. Each time carries its own cap, "HH:mm=N": at most N
# applications per board in that run, spaced a minute or more apart. The
# defaults are 5 in the morning, 5 in the afternoon, 10 in the evening, then
# 10 more twice in the night, 4-5 hours apart - 40 a day per board, in small
# batches, which is how a person applying by hand looks and how neither board
# gets a burst to flag. What a run does not reach stays in the backlog and is
# picked up by the next one. -NightTimes run jobs_scan.bat (scan + apply, no
# interview prep) whatever -Mode says, so the night runs cost no tokens.
#
# NOTHING APPEARS ON SCREEN WHILE A RUN WORKS. The task does not start the
# batch file directly - that would open a console window for the whole run -
# but goes through scripts\run_hidden.vbs, which starts it with its window
# hidden and sets NAUKRI_BACKGROUND=1 so the browser runs headless (see
# naukri\session.py). Everything the batch prints lands in logs\scheduled.log.
#
# The tasks still run interactively (not "whether user is logged on or not"):
# if Naukri ever refuses the headless browser again, the fallback is a headed
# window parked off-screen, and that needs a desktop session to exist. Stay
# logged in to Windows; the lock screen is fine.

param(
    # scan     search both boards, score, write the openings page. Free.
    # scanprep the same, then build that scan's Top 10 into a 100-question
    #          study page. Each run claims its own file (run 1, 2, 3), so the
    #          afternoon never overwrites the morning. Costs model tokens -
    #          roughly $5-6 for the first run of a day, less for later runs
    #          where the Top 10 has barely moved and questions carry over.
    # scanpublish scan, then push the new openings page to the phone site
    #          (jobs_scan_and_publish.bat; set up once with site\setup_phone.bat).
    # scan3    at 10:00 and 16:00, three scans back to back - last 24h, early
    #          applicant, all jobs - then publish all three to the phone site
    #          (jobs_scan_3way.bat). Ignores -Times/-NightTimes.
    # apply    submit real applications. Read jobs_agent.bat before using it.
    [ValidateSet("scan", "scanprep", "scanpublish", "scan3", "apply")]
    [string]$Mode = "scan",
    [switch]$Remove,
    [string[]]$Times = @("08:52=5", "13:23=5", "18:11=10"),
    [string[]]$NightTimes = @("23:07=10", "04:23=10")
)

$ErrorActionPreference = "Stop"

$root   = Split-Path -Parent $PSScriptRoot
$prefix = "NaukriJobAgent"
$batch  = switch ($Mode) {
    "apply"    { Join-Path $root "jobs_agent.bat" }
    "scanprep" { Join-Path $root "jobs_scan_and_prep.bat" }
    "scanpublish" { Join-Path $root "jobs_scan_and_publish.bat" }
    "scan3"    { Join-Path $root "jobs_scan_3way.bat" }
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

$launcher = Join-Path $PSScriptRoot "run_hidden.vbs"
if (-not (Test-Path $launcher)) {
    throw "Cannot find $launcher"
}

# wscript.exe has no console of its own, and run_hidden.vbs starts the batch
# with its window hidden - so no cmd window, and no Chrome window either.
$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\wscript.exe" `
    -Argument "//B //Nologo `"$launcher`" `"$batch`"" `
    -WorkingDirectory $root

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

# Three scans plus publishing take far longer than one scan.
if ($Mode -eq "scan3") {
    $Times = @("10:00=5", "16:00=5")
    $NightTimes = @()
    $settings.ExecutionTimeLimit = "PT4H"
}

$scanOnly = Join-Path $root "jobs_scan.bat"
$slots = @()
foreach ($t in $Times)      { $slots += @{ spec = $t; batch = $batch;    mode = $Mode } }
foreach ($t in $NightTimes) { $slots += @{ spec = $t; batch = $scanOnly; mode = "scan (night)" } }

$i = 0
foreach ($slot in $slots) {
    $i++
    $time, $limit = $slot.spec -split "=", 2
    if (-not $limit) { $limit = "" }
    $name = "$prefix-$i"
    $argument = "//B //Nologo `"$launcher`" `"$($slot.batch)`""
    if ($limit) { $argument += " NAUKRI_APPLY_LIMIT=$limit" }
    $slotAction = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\wscript.exe" `
        -Argument $argument `
        -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Daily -At $time
    $capText = if ($limit) { "up to $limit applies per board" } else { "daily caps only" }
    Register-ScheduledTask `
        -TaskName $name `
        -Action $slotAction `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Naukri + LinkedIn job agent ($($slot.mode)) - run $i of $($slots.Count), $capText." | Out-Null
    Write-Host "Scheduled $name at $time  ($($slot.mode), $capText)"
}

# scan3 also gets a catch-up task: whenever the laptop wakes from sleep, you
# log on, or you unlock it, jobs_catchup.bat runs whichever of the current
# slot's three scans are missing (none before 10:00; nothing if all are there).
# The 2-minute delay lets Wi-Fi come back first; scan3.py also waits for it.
if ($Mode -eq "scan3") {
    $catchup = Join-Path $root "jobs_catchup.bat"
    $catchAction = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\wscript.exe" `
        -Argument "//B //Nologo `"$launcher`" `"$catchup`" NAUKRI_APPLY_LIMIT=5" `
        -WorkingDirectory $root
    $logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $logon.Delay = "PT2M"
    $unlockClass = Get-CimClass -Namespace Root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskSessionStateChangeTrigger
    $unlock = New-CimInstance -CimClass $unlockClass -ClientOnly -Property @{
        StateChange = 8; UserId = "$env:USERDOMAIN\$env:USERNAME"; Delay = "PT2M"; Enabled = $true }
    $eventClass = Get-CimClass -Namespace Root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskEventTrigger
    $wake = New-CimInstance -CimClass $eventClass -ClientOnly -Property @{
        Enabled = $true; Delay = "PT2M"
        Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name=''Microsoft-Windows-Power-Troubleshooter''] and EventID=1]]</Select></Query></QueryList>' }
    # ...and when a network connects (NetworkProfile 10000): a run that lost
    # Wi-Fi half-way fills in its missing scans as soon as it is back.
    $net = New-CimInstance -CimClass $eventClass -ClientOnly -Property @{
        Enabled = $true; Delay = "PT1M"
        Subscription = '<QueryList><Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational"><Select Path="Microsoft-Windows-NetworkProfile/Operational">*[System[EventID=10000]]</Select></Query></QueryList>' }
    Register-ScheduledTask `
        -TaskName "$prefix-Catchup" `
        -Action $catchAction `
        -Trigger @($logon, $unlock, $wake, $net) `
        -Settings $settings `
        -Description "Naukri job agent catch-up: after wake/logon/unlock, run the 10:00/16:00 scans that are missing today, then publish." | Out-Null
    Write-Host "Scheduled $prefix-Catchup on wake from sleep, logon, unlock and network reconnect"
}

Write-Host ""
Write-Host "Mode: $Mode  ->  $(Split-Path -Leaf $batch)   night runs -> jobs_scan.bat"
Write-Host "Check them with:   Get-ScheduledTask -TaskName '$prefix*'"
Write-Host "Run one now with:  Start-ScheduledTask -TaskName '$prefix-1'"
Write-Host "Stop them with:    ...\schedule_jobs_agent.ps1 -Remove"
Write-Host ""
Write-Host "Each run rewrites data\jobs\openings-<date>.html - your tracker page."
Write-Host "Runs are silent (no console, no browser window); their output is in logs\scheduled.log."
