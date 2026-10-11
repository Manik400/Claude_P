# Keep the PC online and the phone told about it. Runs every 2 minutes (task NetReconnect).
#
#   powershell -ExecutionPolicy Bypass -File scripts\net_watch.ps1          one check (what the task runs)
#   powershell -ExecutionPolicy Bypass -File scripts\net_watch.ps1 -Verbose say what was checked even when all is well
#
# Online:
#   * every HEARTBEAT_MIN minutes a heartbeat goes to the phone (site\tools\phone_apply.py --heartbeat),
#     naming the runs in progress - so a 100-minute apply pass no longer reads as "PC not checked in"
#     (the runs themselves only pushed one at their start or end);
#   * the first check after an outage says how long the PC was offline, and starts the phone
#     queue and the hourly round at once instead of waiting for their next slot.
# Offline:
#   * reconnect Wi-Fi: the profile the adapter last used, then every other saved profile whose
#     SSID is in range, strongest first. Windows itself tries a dropped hotspot once and gives
#     up - on 2026-10-10 the PC sat awake and offline for 13 hours that way.
#   Nothing needs elevation; the adapter is never reset.
# State in logs\net_watch.state.json; output only when something happened -> logs\net_watch.log.
param([switch]$Verbose)

$ErrorActionPreference = "SilentlyContinue"
$root  = Split-Path -Parent $PSScriptRoot
$log   = Join-Path $root "logs\net_watch.log"
$state = Join-Path $root "logs\net_watch.state.json"
$site  = Join-Path (Split-Path -Parent $root) "site"
$py    = Join-Path $root ".venv\Scripts\python.exe"
$HEARTBEAT_MIN = 10

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
    $lines = Get-Content $log
    if ($lines.Count -gt 2000) { $lines | Select-Object -Last 1500 | Set-Content $log -Encoding utf8 }
}

function Load-State {
    try { $s = Get-Content $state -Raw | ConvertFrom-Json } catch { $s = $null }
    if (-not $s) { $s = [pscustomobject]@{ online = $true; offline_since = ""; last_heartbeat = "" } }
    return $s
}
function Save-State($s) { $s | ConvertTo-Json -Compress | Set-Content $state -Encoding utf8 }

function Running-Tasks {
    (Get-ScheduledTask -TaskName "JobHuntApply", "PhoneApplyQueue", "NaukriJobAgent-Scan3" -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Running" } | ForEach-Object { $_.TaskName }) -join ", "
}

function Heartbeat($note) {
    if (-not (Test-Path $py) -or -not (Test-Path (Join-Path $site "tools\phone_apply.py"))) { return $false }
    Push-Location $site
    try {
        $out = & $py "tools\phone_apply.py" --heartbeat $note 2>&1
        $ok = ($LASTEXITCODE -eq 0) -and -not ($out -match "push failed")
    } finally { Pop-Location }
    if (-not $ok) { Say ("heartbeat not sent: " + (($out | Select-Object -Last 1) -replace "\s+", " ")) }
    return $ok
}

function Kick($name) {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($t -and $t.State -ne "Running") { Start-ScheduledTask -TaskName $name; return $name }
    return $null
}

$s = Load-State
$now = Get-Date

if (Online) {
    $note = $null
    if (-not $s.online) {
        # back after an outage: say so, and get the runs going now
        $since = $s.offline_since
        $mins = ""
        try { $mins = " ({0:N0} min)" -f ($now - [datetime]$since).TotalMinutes } catch { }
        $kicked = @(Kick "PhoneApplyQueue"; Kick "JobHuntApply") | Where-Object { $_ }
        Say ("back online - offline since {0}{1}; started: {2}" -f $since, $mins, $(if ($kicked) { $kicked -join ", " } else { "nothing (runs already going)" }))
        $note = "back online; was offline since $since$mins"
        $s.online = $true; $s.offline_since = ""
    } else {
        $due = $true
        try { $due = ($now - [datetime]$s.last_heartbeat).TotalMinutes -ge $HEARTBEAT_MIN } catch { }
        if ($due) {
            $busy = Running-Tasks
            $note = $(if ($busy) { "online; running: $busy" } else { "online; idle" })
        }
    }
    if ($note) {
        if (Heartbeat $note) { $s.last_heartbeat = $now.ToString("s") }
    } elseif ($Verbose) { Write-Host ("[{0}] online" -f $now.ToString("HH:mm:ss")) }
    Save-State $s
    return
}

# ---------------------------------------------------------------------------- offline
if ($s.online) {
    $s.online = $false; $s.offline_since = $now.ToString("yyyy-MM-dd HH:mm")
    Save-State $s
}

# A wired link that is up means the problem is upstream (router / ISP) - nothing to reconnect.
$wired = Get-NetAdapter | Where-Object { $_.Status -eq "Up" -and $_.MediaType -eq "802.3" -and $_.Name -notmatch "Bluetooth" }
$wlan  = netsh wlan show interfaces
$wstate = ($wlan | Select-String '^\s*State\s*:\s*(.+)$').Matches.Groups[1].Value
$last   = ($wlan | Select-String '^\s*Profile\s*:\s*(.+)$').Matches.Groups[1].Value
Say ("offline since {0} (wi-fi: {1}{2}{3})" -f $s.offline_since, $wstate, $(if ($last) { " on $last" } else { "" }), $(if ($wired) { "; wired link up" } else { "" }))

$saved = @((netsh wlan show profiles | Select-String ':\s*(.+)$' | Where-Object { $_.Line -match "Profile\s*:" }) |
    ForEach-Object { $_.Matches.Groups[1].Value.Trim() } | Where-Object { $_ })
$visible = @{}
$ssid = $null
foreach ($line in (netsh wlan show networks mode=bssid)) {
    if ($line -match '^\s*SSID \d+\s*:\s*(.*)$') { $ssid = $Matches[1].Trim() }
    elseif ($ssid -and $line -match '^\s*Signal\s*:\s*(\d+)%') {
        $sig = [int]$Matches[1]
        if (-not $visible.ContainsKey($ssid) -or $visible[$ssid] -lt $sig) { $visible[$ssid] = $sig }
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
    if (Online) {
        $since = $s.offline_since
        $kicked = @(Kick "PhoneApplyQueue"; Kick "JobHuntApply") | Where-Object { $_ }
        Say ("back online via '{0}' - offline since {1}; started: {2}" -f $name, $since, $(if ($kicked) { $kicked -join ", " } else { "nothing (runs already going)" }))
        if (Heartbeat "back online via $name; was offline since $since") { $s.last_heartbeat = (Get-Date).ToString("s") }
        $s.online = $true; $s.offline_since = ""
        Save-State $s
        return
    }
}
Say "still offline after trying: $($order -join ', ')"
