# Builds dist\PocketDeskAgent\PocketDeskAgent.exe (PyInstaller, one-folder) and a zip. No admin required.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location "$root\agent"
python -m pip install --quiet pyinstaller
python -m PyInstaller --noconfirm --clean --name PocketDeskAgent --windowed `
  --distpath "$root\dist" --workpath "$root\build" --specpath "$root\build" `
  --collect-all aiortc --collect-all av --collect-all aioice --collect-all pylibsrtp --collect-all dxcam --collect-submodules comtypes `
  --hidden-import win32timezone --hidden-import win32crypt --hidden-import win32clipboard `
  --paths "$root\agent" "$root\agent\run_agent.py"
Copy-Item "$root\tools\install_agent.ps1" "$root\dist\PocketDeskAgent\" -Force
Copy-Item "$root\tools\uninstall_agent.ps1" "$root\dist\PocketDeskAgent\" -Force
Compress-Archive -Path "$root\dist\PocketDeskAgent" -DestinationPath "$root\dist\PocketDeskAgent-win64.zip" -Force
Write-Host "Built $root\dist\PocketDeskAgent-win64.zip"
