# Run the job hunt (worldwide search + Naukri scan; LinkedIn Easy Apply, Naukri and company sites) over and over,
# silently: each round starts -Gap minutes after the previous one FINISHED.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobhunt.ps1                  start now, then 30 min after each round
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobhunt.ps1 -Gap 30 -Limit 5
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobhunt.ps1 -Remove
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobhunt.ps1 -Show           when is the next round
#
# How the "gap after it finishes" works: the task JobHuntApply has a one-time
# trigger that jobhunt_hourly.bat moves forward at the end of every round (to
# finish time + Gap). At the start of a round it is set to start + MaxMinutes
# + Gap as a backstop, so a round that crashes or is killed still gets a next
# one. A logon trigger restarts the chain after a reboot.
#
# Each round repeats your last worldwide search, then runs the Naukri scan, and
# applies to at most -Limit postings per board (Naukri, LinkedIn Easy Apply,
# company sites that need no login), each apply pass stopping new applications
# after -ApplyMinutes. The LinkedIn daily cap in
# ..\Profile_Naukri_Screener-main\jobs.yaml still bounds the day. Nothing
# appears on screen (run_hidden.vbs, headless browser); output goes to
# ..\Profile_Naukri_Screener-main\logs\scheduled.log. Runs only while you are
# logged on and the PC is awake.

param(
    [switch]$Remove,
    [switch]$Rearm,
    [switch]$Backstop,
    [switch]$Show,
    [int]$Gap = 30,
    [int]$Limit = 5,
    [int]$ApplyMinutes = 25,
    [int]$MaxMinutes = 120
)

$ErrorActionPreference = "Stop"

$root     = Split-Path -Parent $PSScriptRoot
$name     = "JobHuntApply"
$batch    = Join-Path $root "jobhunt_hourly.bat"
$sibling  = Join-Path (Split-Path -Parent $root) "Profile_Naukri_Screener-main"
$launcher = Join-Path $sibling "scripts\run_hidden.vbs"

function Show-Next {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "$name is not scheduled."; return }
    $i = $t | Get-ScheduledTaskInfo
    Write-Host "${name}  state=$($t.State)  last run=$($i.LastRunTime)  last result=$($i.LastTaskResult)  next run=$($i.NextRunTime)"
    Write-Host "  $($t.Description)"
}

if ($Show) { Show-Next; return }

if ($Rearm) {
    # Called by jobhunt_hourly.bat: move the one-time trigger, keep the logon one.
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) { return }
    $gapMin = $Gap; $maxMin = $MaxMinutes
    if ($task.Description -match "gap=(\d+) max=(\d+)") { $gapMin = [int]$Matches[1]; $maxMin = [int]$Matches[2] }
    $minutes = if ($Backstop) { $maxMin + $gapMin } else { $gapMin }
    $next    = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes($minutes)
    $logon   = $task.Triggers | Where-Object { $_.CimClass.CimClassName -eq "MSFT_TaskLogonTrigger" }
    Set-ScheduledTask -TaskName $name -Trigger @(@($next) + @($logon)) | Out-Null
    Write-Host ("[{0}] {1}: next round at {2}{3}" -f (Get-Date -Format HH:mm:ss), $name,
        (Get-Date).AddMinutes($minutes).ToString("HH:mm"), $(if ($Backstop) { " (backstop, moved when this round ends)" } else { "" }))
    return
}

foreach ($path in @($batch, $launcher)) {
    if (-not (Test-Path $path)) { throw "Cannot find $path" }
}

# The old fixed daily slots (JobHuntApply-1, -2) and any earlier JobHuntApply.
Get-ScheduledTask -TaskName "$name*" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing existing task $($_.TaskName)"
        Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
    }

if ($Remove) {
    Write-Host "Job hunt apply unscheduled."
    return
}

# Same battery flags as the Naukri screener's scheduler - without them a
# laptop on battery silently skips or kills the run.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $MaxMinutes) `
    -MultipleInstances IgnoreNew

$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\wscript.exe" `
    -Argument "//B //Nologo `"$launcher`" `"$batch`" NAUKRI_APPLY_LIMIT=$Limit APPLY_MAX_MINUTES=$ApplyMinutes" `
    -WorkingDirectory $root

$first = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(30)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logon.Delay = "PT5M"

Register-ScheduledTask `
    -TaskName $name `
    -Action $action `
    -Trigger @($first, $logon) `
    -Settings $settings `
    -Description "Job hunt: worldwide search + Naukri scan, apply up to $Limit per board (Naukri, LinkedIn Easy Apply, company sites without login), then again $Gap min after it finishes. gap=$Gap max=$MaxMinutes" | Out-Null

Write-Host "Scheduled ${name}: first round in 30 s, then $Gap min after each round finishes (and 5 min after logon)."
Write-Host "Up to $Limit applies per board per round, no new applies after $ApplyMinutes min, hard stop at $MaxMinutes min."
Write-Host ""
Write-Host "Next round:  ...\schedule_jobhunt.ps1 -Show"
Write-Host "Run now:     Start-ScheduledTask -TaskName '$name'"
Write-Host "Stop it:     ...\schedule_jobhunt.ps1 -Remove"
Write-Host "Output:      ..\Profile_Naukri_Screener-main\logs\scheduled.log"
