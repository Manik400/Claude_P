# Keep the LinkedIn Premium runner going for as long as Premium is paid for.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_linkedin_premium.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_linkedin_premium.ps1 -Remove
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_linkedin_premium.ps1 -Show
#
# The task LinkedInPremium starts naukri\jobs\linkedin_premium.py --loop with pythonw.exe (no window,
# headless browser). The loop does a pass every `every_minutes` (data\premium\premium.yaml, default
# 240) and exits by itself the day after `until`. The task fires 4 minutes after every logon and
# checks every 30 minutes that the loop is still running (IgnoreNew leaves a running one alone).
# Output: logs\linkedin_premium.log. Report: data\premium\LATEST.md.
#
# Needs the saved LinkedIn session (python main.py --linkedin-login, once).

param(
    [switch]$Remove,
    [switch]$Show
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$name = "LinkedInPremium"

function Show-Status {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "$name is not scheduled."; return }
    $i = $t | Get-ScheduledTaskInfo
    Write-Host "${name}  state=$($t.State)  last start=$($i.LastRunTime)  last result=$($i.LastTaskResult)  next check=$($i.NextRunTime)"
    Write-Host "  $($t.Description)"
    $log = Join-Path $root "logs\linkedin_premium.log"
    if (Test-Path $log) { Write-Host "  last log lines:"; Get-Content $log -Tail 8 | ForEach-Object { Write-Host "    $_" } }
}

if ($Show) { Show-Status; return }

Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing existing task $($_.TaskName)"
        Stop-ScheduledTask -TaskName $_.TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
    }

if ($Remove) {
    Write-Host "LinkedIn Premium runner unscheduled."
    return
}

$py = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path $py)) { throw "Cannot find the project's Python at $py - create the venv first (see README)" }
if (-not (Test-Path (Join-Path $root "naukri\jobs\linkedin_premium.py"))) { throw "Cannot find naukri\jobs\linkedin_premium.py" }

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit = "PT0S"

$action = New-ScheduledTaskAction `
    -Execute $py `
    -Argument "-m naukri.jobs.linkedin_premium --loop" `
    -WorkingDirectory $root

$check = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT4M"

Register-ScheduledTask `
    -TaskName $name `
    -Action $action `
    -Trigger @($check, $logon) `
    -Settings $settings `
    -Description "LinkedIn Premium runner: Top Applicant + abroad jobs, Easy Apply, viewers -> leads, InMail drafts, a like and a post draft a day. Stops itself after the Premium end date in data\premium\premium.yaml. Restarted if it stops." | Out-Null

Write-Host "Scheduled ${name}: starts within a minute and after every logon; a pass every 4 h (premium.yaml: every_minutes)."
Write-Host "Status:   ...\schedule_linkedin_premium.ps1 -Show"
Write-Host "Run now:  Start-ScheduledTask -TaskName '$name'"
Write-Host "Stop it:  ...\schedule_linkedin_premium.ps1 -Remove"
Write-Host "Report:   data\premium\LATEST.md     Log: logs\linkedin_premium.log"
