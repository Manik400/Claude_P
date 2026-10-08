# Labeling of the posts dataset by the big local model, all day (naukri\jobs\post_model.py --run).
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_post_labeling.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_post_labeling.ps1 -Remove
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_post_labeling.ps1 -Show
#
# Task PostLabeling starts 3 minutes after every logon and is checked every 15 minutes (a running one is
# left alone - IgnoreNew). Each run gathers the posts the watchers added, labels everything still unlabeled
# (the posts you label on the phone first, then the ones the rules are unsure about), retrains the small
# classifier when there are enough new labels, and exits; the next check starts it again. Below-normal
# priority, so the other loops keep their speed. Resumable at any point. Needs no network: the model is
# local, so a dropped connection changes nothing here. Output: logs\post_model.log.

param(
    [switch]$Remove,
    [switch]$Show
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$name = "PostLabeling"

function Show-Status {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "$name is not scheduled."; return }
    $i = $t | Get-ScheduledTaskInfo
    Write-Host "${name}  state=$($t.State)  last start=$($i.LastRunTime)  last result=$($i.LastTaskResult)  next check=$($i.NextRunTime)"
    $log = Join-Path $root "logs\post_model.log"
    if (Test-Path $log) { Write-Host "  last log lines:"; Get-Content $log -Tail 5 | ForEach-Object { Write-Host "    $_" } }
}

if ($Show) { Show-Status; return }

Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing existing task $($_.TaskName)"
        Stop-ScheduledTask -TaskName $_.TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
    }

if ($Remove) {
    Write-Host "Post labeling unscheduled."
    return
}

$py = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path $py)) { throw "Cannot find the project's Python at $py" }

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -Priority 8 `
    -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit = "PT0S"

$action = New-ScheduledTaskAction -Execute $py -Argument "-m naukri.jobs.post_model --run" -WorkingDirectory $root
$check = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT3M"

Register-ScheduledTask -TaskName $name -Action $action -Trigger @($check, $logon) -Settings $settings `
    -Description "All day: the big local model labels the posts dataset (most useful first) and retrains the post classifier; restarted after logon or if it stops; no network needed." | Out-Null

Write-Host "Scheduled ${name}: starts within a minute, 3 minutes after every logon, checked every 15 minutes; below-normal priority."
Write-Host "Status:   ...\schedule_post_labeling.ps1 -Show"
Write-Host "Output:   logs\post_model.log"
