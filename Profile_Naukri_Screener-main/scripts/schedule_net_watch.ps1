# Keep the PC online: the task NetReconnect runs scripts\net_watch.ps1 every
# 2 minutes (hidden) and reconnects Wi-Fi to a saved network in range whenever
# the internet is gone. See net_watch.ps1 for why.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_net_watch.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_net_watch.ps1 -Every 5
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_net_watch.ps1 -Remove
param(
    [switch]$Remove,
    [int]$Every = 2
)

$ErrorActionPreference = "Stop"
$name = "NetReconnect"
$vbs  = Join-Path $PSScriptRoot "net_watch.vbs"
if (-not (Test-Path $vbs)) { throw "Cannot find $vbs" }

Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue |
    ForEach-Object { Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false }
if ($Remove) { Write-Host "$name unscheduled."; return }

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

$action  = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wscript.exe" `
    -Argument "//B //Nologo `"$vbs`"" -WorkingDirectory $PSScriptRoot
$repeat  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $Every)
$logon   = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT1M"

Register-ScheduledTask -TaskName $name -Action $action -Trigger @($repeat, $logon) -Settings $settings `
    -Description "Reconnects Wi-Fi to a saved network in range whenever the internet is gone; checks every $Every min (scripts\net_watch.ps1). Log: logs\net_watch.log" | Out-Null
Write-Host "Scheduled ${name}: every $Every min and after logon. Log: logs\net_watch.log"
