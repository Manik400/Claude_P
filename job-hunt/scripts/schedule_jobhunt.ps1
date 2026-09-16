# Schedule the worldwide job hunt to search and apply, silently, twice a day.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobhunt.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobhunt.ps1 -Times @("11:47=5","21:19=5")
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobhunt.ps1 -Remove
#
# Each run repeats your last search (same roles, experience, countries and
# resume) and then applies to the LinkedIn postings it found - at most N per
# run ("HH:mm=N"), a minute or more apart. The two default slots sit between
# the Naukri screener's runs (08:52, 13:23, 18:11, 23:07, 04:23), and the
# LinkedIn daily cap in that project's jobs.yaml bounds both projects
# together, so LinkedIn never sees more than that in a day from either.
#
# Nothing appears on screen: the task goes through the Naukri screener's
# scripts\run_hidden.vbs (hidden console, headless browser). Output lands in
# ..\Profile_Naukri_Screener-main\logs\scheduled.log. The tasks run only when
# you are logged on - the headless browser needs a desktop session to fall
# back to if LinkedIn ever refuses it.

param(
    [switch]$Remove,
    [string[]]$Times = @("11:47=5", "21:19=5")
)

$ErrorActionPreference = "Stop"

$root     = Split-Path -Parent $PSScriptRoot
$prefix   = "JobHuntApply"
$batch    = Join-Path $root "jobhunt_apply.bat"
$sibling  = Join-Path (Split-Path -Parent $root) "Profile_Naukri_Screener-main"
$launcher = Join-Path $sibling "scripts\run_hidden.vbs"

foreach ($path in @($batch, $launcher)) {
    if (-not (Test-Path $path)) { throw "Cannot find $path" }
}

Get-ScheduledTask -TaskName "$prefix*" -ErrorAction SilentlyContinue |
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
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

$i = 0
foreach ($spec in $Times) {
    $i++
    $time, $limit = $spec -split "=", 2
    if (-not $limit) { $limit = "" }
    $name = "$prefix-$i"
    $argument = "//B //Nologo `"$launcher`" `"$batch`""
    if ($limit) { $argument += " NAUKRI_APPLY_LIMIT=$limit" }
    $action = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\wscript.exe" `
        -Argument $argument `
        -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Daily -At $time
    $capText = if ($limit) { "up to $limit applies" } else { "daily cap only" }
    Register-ScheduledTask `
        -TaskName $name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Worldwide job hunt: search like last run, then LinkedIn Easy Apply - run $i of $($Times.Count), $capText." | Out-Null
    Write-Host "Scheduled $name at $time  ($capText)"
}

Write-Host ""
Write-Host "Check them with:   Get-ScheduledTask -TaskName '$prefix*'"
Write-Host "Run one now with:  Start-ScheduledTask -TaskName '$prefix-1'"
Write-Host "Stop them with:    ...\schedule_jobhunt.ps1 -Remove"
Write-Host "Output:            ..\Profile_Naukri_Screener-main\logs\scheduled.log"
