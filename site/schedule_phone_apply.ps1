# Poll the phone's auto-apply queue every N minutes, silently.
#
#   powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1
#   powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1 -Every 30 -Limit 5
#   powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1 -Remove
#
# Each poll refreshes the gh-pages clone, applies to at most -Limit of the
# postings the phone asked for (a minute or more apart), and publishes the
# status back. A request for many postings is finished over several polls,
# and the daily LinkedIn cap in Profile_Naukri_Screener-main\jobs.yaml still
# bounds everything. Nothing appears on screen (run_hidden.vbs); output is in
# Profile_Naukri_Screener-main\logs\scheduled.log. Runs only while you are
# logged on - the headless browser needs a desktop session to fall back to.

param(
    [switch]$Remove,
    [int]$Every = 30,
    [int]$Limit = 5
)

$ErrorActionPreference = "Stop"

$root     = Split-Path -Parent $PSScriptRoot
$name     = "PhoneApplyQueue"
$batch    = Join-Path $PSScriptRoot "phone_apply.bat"
$launcher = Join-Path $root "Profile_Naukri_Screener-main\scripts\run_hidden.vbs"

foreach ($path in @($batch, $launcher)) {
    if (-not (Test-Path $path)) { throw "Cannot find $path" }
}

Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Removing existing task $($_.TaskName)"
        Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
    }

if ($Remove) {
    Write-Host "Phone apply queue unscheduled."
    return
}

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 50) `
    -MultipleInstances IgnoreNew

$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\wscript.exe" `
    -Argument "//B //Nologo `"$launcher`" `"$batch`" NAUKRI_APPLY_LIMIT=$Limit" `
    -WorkingDirectory $PSScriptRoot

# Repeats every -Every minutes, indefinitely, starting a few minutes from now.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(3) `
    -RepetitionInterval (New-TimeSpan -Minutes $Every)

Register-ScheduledTask `
    -TaskName $name `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Phone auto-apply queue: every $Every min, up to $Limit LinkedIn applies per poll." | Out-Null

Write-Host "Scheduled $name every $Every minutes, up to $Limit applies per poll."
Write-Host "Check it with:   Get-ScheduledTask -TaskName '$name'"
Write-Host "Run it now with: Start-ScheduledTask -TaskName '$name'"
Write-Host "Stop it with:    ...\schedule_phone_apply.ps1 -Remove"
