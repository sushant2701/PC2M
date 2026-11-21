# LAN/dev signaling server on http://0.0.0.0:8080 (NOT for internet exposure: no TLS). Use signaling\deploy for production.
$env:HOST = "0.0.0.0"; $env:PORT = "8080"
Set-Location "$PSScriptRoot\..\signaling"
python -m pocketdesk_signaling.app
