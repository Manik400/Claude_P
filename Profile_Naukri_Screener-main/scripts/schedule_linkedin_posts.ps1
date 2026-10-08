# Keep the LinkedIn hiring-posts watcher running for as long as the PC is on.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_linkedin_posts.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_linkedin_posts.ps1 -Every 30 -Hours 12
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_linkedin_posts.ps1 -Remove
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_linkedin_posts.ps1 -Show
#
# The task LinkedInPostsWatch starts naukri\jobs\linkedin_posts.py --loop, which reads LinkedIn's
# post search ("hiring software engineer", "hiring SDE", "hiring freshers software"...) in a
# headless browser every -Every minutes, keeps the hiring posts for 0-2 years from the last
# -Hours hours and publishes them to the phone site's Posts tab. It runs with pythonw.exe, so
# nothing appears on screen, and has no time limit: one process keeps going all day. The task
# fires 3 minutes after every logon and checks every 30 minutes - a watcher that is still
# running is left alone (IgnoreNew); one that stopped is started again. Output:
# logs\linkedin_posts.log.
#
# Needs the saved LinkedIn session (python main.py --linkedin-login, once). This only READS
# LinkedIn: nothing is liked, commented on or messaged.

param(
    [switch]$Remove,
    [switch]$Show,
    [int]$Every = 30,
    [int]$Hours = 48,
    [int]$PerPass = 8
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$name = "LinkedInPostsWatch"

function Show-Status {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "$name is not scheduled."; return }
    $i = $t | Get-ScheduledTaskInfo
    Write-Host "${name}  state=$($t.State)  last start=$($i.LastRunTime)  last result=$($i.LastTaskResult)  next check=$($i.NextRunTime)"
    Write-Host "  $($t.Description)"
    $log = Join-Path $root "logs\linkedin_posts.log"
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
    Write-Host "LinkedIn posts watcher unscheduled."
    return
}

# pythonw.exe: no console window at all. The venv has it next to python.exe.
$py = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path $py)) { throw "Cannot find the project's Python at $py - create the venv first (see README)" }
if (-not (Test-Path (Join-Path $root "naukri\jobs\linkedin_posts.py"))) { throw "Cannot find naukri\jobs\linkedin_posts.py" }

# Same battery flags as the other tasks (a laptop on battery would otherwise skip or kill it).
# No time limit: this process is meant to run all day.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit = "PT0S"

$action = New-ScheduledTaskAction `
    -Execute $py `
    -Argument "-m naukri.jobs.linkedin_posts --loop --every $Every --hours $Hours --per-pass $PerPass" `
    -WorkingDirectory $root

# Start in a minute and check every 30 minutes forever (a running watcher is left alone),
# plus 3 minutes after every logon.
$check = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT3M"

Register-ScheduledTask `
    -TaskName $name `
    -Action $action `
    -Trigger @($check, $logon) `
    -Settings $settings `
    -Description "LinkedIn hiring posts: every $Every min, posts from the last $Hours h for 0-2 yrs software roles, published to the phone's Posts tab. Restarted if it stops." | Out-Null

Write-Host "Scheduled ${name}: the watcher starts within a minute and after every logon; a pass every $Every min, posts from the last $Hours h."
Write-Host "Status:   ...\schedule_linkedin_posts.ps1 -Show"
Write-Host "Run now:  Start-ScheduledTask -TaskName '$name'"
Write-Host "Stop it:  ...\schedule_linkedin_posts.ps1 -Remove"
Write-Host "Output:   logs\linkedin_posts.log"
