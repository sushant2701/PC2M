# One-click start: signaling server + self-restarting tunnel + agent (all hidden except the agent window). No admin needed.
$root = Split-Path $PSScriptRoot -Parent
if (-not (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue)) {
  $env:HOST = "127.0.0.1"; $env:PORT = "8080"
  Start-Process python -ArgumentList '-m', 'pocketdesk_signaling.app' -WorkingDirectory "$root\signaling" -WindowStyle Hidden
  Start-Sleep 3
}
if (-not (Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | ? { $_.CommandLine -match 'tunnel_supervisor' })) {
  Start-Process powershell -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', "$PSScriptRoot\tunnel_supervisor.ps1" -WindowStyle Hidden
}
Push-Location "$root\agent"; python -m pocketdesk_agent config --server http://127.0.0.1:8080 | Out-Null; Pop-Location
if (-not (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? { $_.CommandLine -match '-m pocketdesk_agent' })) {
  Start-Process python -ArgumentList '-m', 'pocketdesk_agent' -WorkingDirectory "$root\agent"
}
Write-Host "Started. In the agent window click 'Pair a new phone' and scan the QR. Phone address: $env:APPDATA\PocketDesk\public_url.txt"
