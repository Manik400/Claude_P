# Keep the social hiring-posts watcher (X, Telegram, Reddit, HN, Mastodon, Bluesky) running while the PC is on.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_social_posts.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_social_posts.ps1 -Every 30 -Hours 12
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_social_posts.ps1 -Remove
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_social_posts.ps1 -Show
#
# The task SocialPostsWatch starts naukri\jobs\social_posts.py --loop with pythonw.exe (nothing on screen).
# It fires 3 minutes after every logon and checks every 30 minutes; a running watcher is left alone.
# Output: logs\social_posts.log. X needs a saved session (social_posts.bat --login-x) and is skipped without one.

param(
    [switch]$Remove,
    [switch]$Show,
    [int]$Every = 30,
    [int]$Hours = 12
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$name = "SocialPostsWatch"

function Show-Status {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "$name is not scheduled."; return }
    $i = $t | Get-ScheduledTaskInfo
    Write-Host "${name}  state=$($t.State)  last start=$($i.LastRunTime)  last result=$($i.LastTaskResult)  next check=$($i.NextRunTime)"
    Write-Host "  $($t.Description)"
    $log = Join-Path $root "logs\social_posts.log"
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
    Write-Host "Social posts watcher unscheduled."
    return
}

$py = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path $py)) { throw "Cannot find the project's Python at $py - create the venv first (see README)" }
if (-not (Test-Path (Join-Path $root "naukri\jobs\social_posts.py"))) { throw "Cannot find naukri\jobs\social_posts.py" }

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit = "PT0S"

$action = New-ScheduledTaskAction `
    -Execute $py `
    -Argument "-m naukri.jobs.social_posts --loop --every $Every --hours $Hours" `
    -WorkingDirectory $root

$check = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT3M"

Register-ScheduledTask `
    -TaskName $name `
    -Action $action `
    -Trigger @($check, $logon) `
    -Settings $settings `
    -Description "Hiring posts from X, Telegram, Reddit, HN, Mastodon, Bluesky: every $Every min, posts from the last $Hours h for 0-2 yrs software roles, published to the phone's Posts tab. Restarted if it stops." | Out-Null

Write-Host "Scheduled ${name}: starts within a minute and after every logon; a pass every $Every min."
Write-Host "Status:   ...\schedule_social_posts.ps1 -Show"
Write-Host "Run now:  Start-ScheduledTask -TaskName '$name'"
Write-Host "Stop it:  ...\schedule_social_posts.ps1 -Remove"
Write-Host "Output:   logs\social_posts.log"
