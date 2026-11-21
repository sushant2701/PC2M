# Keeps a public HTTPS tunnel to the local PocketDesk server alive (no admin needed; uses Windows' built-in ssh -> serveo.net).
# Restarts automatically if it drops. Writes the current address to %APPDATA%\PocketDesk\public_url.txt (the agent shows it in the QR).
# For a PERMANENT address register the printed key once at https://console.serveo.net (free Google/GitHub login).
$dir = Join-Path $env:APPDATA "PocketDesk"; New-Item -ItemType Directory -Force $dir | Out-Null
$key = Join-Path $dir "tunnel_key"
if (-not (Test-Path $key)) { ssh-keygen -t ed25519 -N '""' -f $key -q }
$nameFile = Join-Path $dir "tunnel_name.txt"
if (-not (Test-Path $nameFile)) { "pd-" + (-join ((1..8) | % { '{0:x}' -f (Get-Random -Max 16) })) | Set-Content $nameFile }
$name = (Get-Content $nameFile).Trim()
$urlFile = Join-Path $dir "public_url.txt"
while ($true) {
  $out = Join-Path $env:TEMP "pd_tunnel.out"; Remove-Item $out -ErrorAction SilentlyContinue
  # try the reserved name first; serveo falls back to a random address if the key is not registered yet
  $p = Start-Process ssh -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError (Join-Path $env:TEMP "pd_tunnel.err") `
        -ArgumentList '-i', $key, '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', '-o', 'ExitOnForwardFailure=yes', '-R', "${name}:80:127.0.0.1:8080", 'serveo.net'
  $last = ""
  while (-not $p.HasExited) {      # keep the address file in sync with whatever this ssh session printed
    Start-Sleep 2
    if (Test-Path $out) { $m = [regex]::Match((Get-Content $out -Raw), 'https://\S+serveousercontent\.com'); if ($m.Success -and $m.Value -ne $last) { $last = $m.Value; $m.Value | Set-Content $urlFile -NoNewline } }
  }
  Remove-Item $urlFile -ErrorAction SilentlyContinue   # tunnel is down: no valid address
  Start-Sleep 3
}
