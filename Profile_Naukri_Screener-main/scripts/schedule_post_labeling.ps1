# Overnight labeling of the posts dataset by the big local model (naukri\jobs\post_model.py --label).
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_post_labeling.ps1              every night 23:30 -> 07:00
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_post_labeling.ps1 -At 23:30 -StopAt 07:00
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_post_labeling.ps1 -Remove
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_post_labeling.ps1 -Show
#
# Task PostLabeling runs with pythonw.exe at BELOW NORMAL priority (the other loops keep their speed), labels
# the most useful posts first (the ones you label on the phone, then the ones the rules are unsure about),
# and stops itself at -StopAt. It is resumable: every night continues where the last one stopped. When
# nothing is left to label it exits at once. Output: logs\post_model.log. Then: python -m naukri.jobs.post_model --train

param(
    [switch]$Remove,
    [switch]$Show,
    [string]$At = "23:30",
    [string]$StopAt = "07:00"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$name = "PostLabeling"

function Show-Status {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "$name is not scheduled."; return }
    $i = $t | Get-ScheduledTaskInfo
    Write-Host "${name}  state=$($t.State)  last start=$($i.LastRunTime)  last result=$($i.LastTaskResult)  next=$($i.NextRunTime)"
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
$settings.ExecutionTimeLimit = "PT10H"

$action = New-ScheduledTaskAction -Execute $py -Argument "-m naukri.jobs.post_model --label --stop-at $StopAt" -WorkingDirectory $root
$daily = New-ScheduledTaskTrigger -Daily -At $At

Register-ScheduledTask -TaskName $name -Action $action -Trigger $daily -Settings $settings `
    -Description "Overnight: the big local model labels the posts dataset (most useful first), $At to $StopAt, resumable. Then post_model --train." | Out-Null

Write-Host "Scheduled ${name}: every night at $At, stops at $StopAt, below-normal priority, resumable."
Write-Host "Status:   ...\schedule_post_labeling.ps1 -Show"
Write-Host "Run now:  Start-ScheduledTask -TaskName '$name'"
Write-Host "Output:   logs\post_model.log"
