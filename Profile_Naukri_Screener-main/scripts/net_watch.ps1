# Bring the internet back when it drops: every check, if nothing answers,
# reconnect Wi-Fi to a saved network that is in range.
#
#   powershell -ExecutionPolicy Bypass -File scripts\net_watch.ps1          one check (what the task NetReconnect runs every 2 min)
#   powershell -ExecutionPolicy Bypass -File scripts\net_watch.ps1 -Verbose say what was checked even when all is well
#
# Why: on 2026-10-10 the Wi-Fi ("Manik", a phone hotspot) dropped at 21:55.
# Windows tried once, failed, and never tried again; the PC sat awake and
# offline for 13 hours while every job-hunt round failed and the phone said
# "PC off". Windows only retries a profile on its own when the network
# reappears and the adapter notices; this asks, every two minutes.
#
# What it does when offline, in order, stopping at the first that works:
#   1. the profile the adapter last used (netsh wlan show interfaces: Profile)
#   2. every other saved profile whose SSID is visible right now, strongest first
# Nothing needs elevation (netsh wlan connect is a user command); the adapter
# is never reset. Output only when something was wrong -> logs\net_watch.log.
param([switch]$Verbose)

$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
$log  = Join-Path $root "logs\net_watch.log"

function Online {
    # Two independent hosts, TCP only (no ICMP, which hotspots often block).
    foreach ($h in @("api.github.com", "www.naukri.com", "1.1.1.1")) {
        try {
            $c = New-Object Net.Sockets.TcpClient
            $ok = $c.ConnectAsync($h, 443).Wait(4000) -and $c.Connected
            $c.Close()
            if ($ok) { return $true }
        } catch { }
    }
    return $false
}

function Say($text) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $text
    if ($Verbose) { Write-Host $line }
    New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
    Add-Content -Path $log -Value $line -Encoding utf8
    # keep the log small
    $lines = Get-Content $log
    if ($lines.Count -gt 2000) { $lines | Select-Object -Last 1500 | Set-Content $log -Encoding utf8 }
}

if (Online) {
    if ($Verbose) { Write-Host ("[{0}] online" -f (Get-Date -Format "HH:mm:ss")) }
    return
}

# A wired link that is up means the problem is upstream (router / ISP) - nothing to reconnect.
$wired = Get-NetAdapter | Where-Object { $_.Status -eq "Up" -and $_.MediaType -eq "802.3" -and $_.Name -notmatch "Bluetooth" }
$wlan  = netsh wlan show interfaces
$state = ($wlan | Select-String '^\s*State\s*:\s*(.+)$').Matches.Groups[1].Value
$last  = ($wlan | Select-String '^\s*Profile\s*:\s*(.+)$').Matches.Groups[1].Value
Say ("offline (wi-fi: {0}{1}{2})" -f $state, $(if ($last) { " on $last" } else { "" }), $(if ($wired) { "; wired link up" } else { "" }))

$saved = @((netsh wlan show profiles | Select-String ':\s*(.+)$' | Where-Object { $_.Line -match "Profile\s*:" }) |
    ForEach-Object { $_.Matches.Groups[1].Value.Trim() } | Where-Object { $_ })
# visible SSIDs with their strongest signal
$visible = @{}
$ssid = $null
foreach ($line in (netsh wlan show networks mode=bssid)) {
    if ($line -match '^\s*SSID \d+\s*:\s*(.*)$') { $ssid = $Matches[1].Trim() }
    elseif ($ssid -and $line -match '^\s*Signal\s*:\s*(\d+)%') {
        $s = [int]$Matches[1]
        if (-not $visible.ContainsKey($ssid) -or $visible[$ssid] -lt $s) { $visible[$ssid] = $s }
    }
}

$order = @()
if ($last -and $saved -contains $last) { $order += $last }
$order += $saved | Where-Object { $_ -ne $last -and $visible.ContainsKey($_) } | Sort-Object { -$visible[$_] }
if (-not $order) {
    Say ("no saved network in range (visible: {0}); will try again" -f (($visible.Keys | Where-Object { $_ }) -join ", "))
    return
}

foreach ($name in $order) {
    $sig = if ($visible.ContainsKey($name)) { "$($visible[$name])%" } else { "not visible" }
    Say ("connecting to '{0}' ({1})" -f $name, $sig)
    netsh wlan connect name="$name" | Out-Null
    Start-Sleep -Seconds 15
    if (Online) { Say ("back online via '{0}'" -f $name); return }
}
Say "still offline after trying: $($order -join ', ')"
