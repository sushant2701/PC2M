# One-click start: signaling server + self-restarting tunnel + agent (all hidden except the agent window). No admin needed.
$root = Split-Path $PSScriptRoot -Parent
if (-not (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue)) {
  $env:HOST = "127.0.0.1"; $env:PORT = "8080"
  Start-Process python -ArgumentList '-m', 'pocketdesk_signaling.app' -WorkingDirectory "$root\signaling" -WindowStyle Hidden
  Start-Sleep 3
}
# The agent now runs and health-checks its own tunnel (config --tunnel on), so the old tunnel_supervisor.ps1 is NOT started.
Push-Location "$root\agent"; python -m pocketdesk_agent config --tunnel on | Out-Null; Pop-Location
if (-not (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? { $_.CommandLine -match '-m pocketdesk_agent' })) {
  Start-Process python -ArgumentList '-m', 'pocketdesk_agent' -WorkingDirectory "$root\agent"
}
Write-Host "Started. In the agent window click 'Pair a new phone' and scan the QR. Phone address: $env:APPDATA\PocketDesk\public_url.txt"
