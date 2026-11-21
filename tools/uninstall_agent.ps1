# Removes the agent, shortcut and autostart entry. Pass -RemoveData to also delete %APPDATA%\PocketDesk (keys, logs).
param([switch]$RemoveData)
Get-Process PocketDeskAgent -ErrorAction SilentlyContinue | Stop-Process
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name PocketDeskAgent -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "PocketDesk Agent.lnk") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $env:LOCALAPPDATA "Programs\PocketDesk") -Recurse -Force -ErrorAction SilentlyContinue
if ($RemoveData) { Remove-Item (Join-Path $env:APPDATA "PocketDesk") -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host "PocketDesk agent removed."
