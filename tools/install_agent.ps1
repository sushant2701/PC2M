# Per-user install (no admin): copies the agent to %LOCALAPPDATA%\Programs\PocketDesk and adds a Start Menu shortcut.
# Autostart at logon is OPT-IN: run with -Autostart. Nothing is installed as a service; no firewall/Defender changes.
param([switch]$Autostart)
$src = $PSScriptRoot
$dst = Join-Path $env:LOCALAPPDATA "Programs\PocketDesk"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item "$src\*" $dst -Recurse -Force
$lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "PocketDesk Agent.lnk"
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk); $s.TargetPath = "$dst\PocketDeskAgent.exe"; $s.WorkingDirectory = $dst; $s.Save()
if ($Autostart) {
  Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name PocketDeskAgent -Value "`"$dst\PocketDeskAgent.exe`""
  Write-Host "Autostart enabled (current user)."
}
Write-Host "Installed to $dst. Start it from the Start Menu: 'PocketDesk Agent'."
