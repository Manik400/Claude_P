# Keep the live job feed (naukri\jobs\live_feed.py) running all day, and again after every reboot / logon.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_live_feed.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_live_feed.ps1 -Remove
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_live_feed.ps1 -Show
#
# Task LiveFeed starts the loop with pythonw.exe (no window), 2 minutes after every logon, and checks
# every 15 minutes that it is still running. Never two at once: the task ignores a new start while one
# runs (IgnoreNew), and the loop itself exits when another live-feed process holds data\live\live.lock.
# Output: logs\live_feed.log. The phone's Live tab reads the feed from the `live` branch.

param(
    [switch]$Remove,
    [switch]$Show
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$name = "LiveFeed"

function Show-Status {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "$name is not scheduled."; return }
    $i = $t | Get-ScheduledTaskInfo
    Write-Host "${name}  state=$($t.State)  last start=$($i.LastRunTime)  last result=$($i.LastTaskResult)  next check=$($i.NextRunTime)"
    $log = Join-Path $root "logs\live_feed.log"
    if (Test-Path $log) { Write-Host "  last log lines:"; Get-Content $log -Tail 6 | ForEach-Object { Write-Host "    $_" } }
}

if ($Show) { Show-Status; return }

Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing existing task $($_.TaskName)"
        Stop-ScheduledTask -TaskName $_.TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
    }

if ($Remove) {
    Write-Host "Live feed unscheduled."
    return
}

$py = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path $py)) { throw "Cannot find the project's Python at $py - create the venv first (see README)" }

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit = "PT0S"

$action = New-ScheduledTaskAction -Execute $py -Argument "-m naukri.jobs.live_feed --loop" -WorkingDirectory $root

$check = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT2M"
$boot  = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = "PT3M"

try {
    Register-ScheduledTask -TaskName $name -Action $action -Trigger @($check, $logon, $boot) -Settings $settings `
        -Description "Live job feed: new LinkedIn postings within minutes (public guest feed, no login) plus hiring posts, published to the phone's Live tab. Restarted after reboot, logon, or if it stops." | Out-Null
} catch {
    # a startup trigger needs admin rights; logon + the 15-minute check cover a reboot anyway
    Register-ScheduledTask -TaskName $name -Action $action -Trigger @($check, $logon) -Settings $settings `
        -Description "Live job feed: new LinkedIn postings within minutes (public guest feed, no login) plus hiring posts, published to the phone's Live tab. Restarted after logon, or if it stops." | Out-Null
}

Write-Host "Scheduled ${name}: starts within a minute, 2 minutes after every logon, and is checked every 15 minutes."
Write-Host "Status:   ...\schedule_live_feed.ps1 -Show"
Write-Host "Stop it:  ...\schedule_live_feed.ps1 -Remove"
Write-Host "Output:   logs\live_feed.log"
