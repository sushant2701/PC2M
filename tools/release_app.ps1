# Builds the Android app and publishes it for in-app auto-update: dist\app\PocketDesk.apk + dist\app\version.json
# (served by the PocketDesk server at /app/...). Bump the build number in android_app\pubspec.yaml (version: 1.1.0+N) first,
# or pass -Bump to increment it. Always build with the SAME signing key (Android refuses updates signed with a different key).
param([switch]$Bump, [string]$Notes = "")
$root = Split-Path $PSScriptRoot -Parent
$pub = "$root\android_app\pubspec.yaml"
$txt = Get-Content $pub -Raw
if ($Bump -and $txt -match 'version:\s*(\d+\.\d+\.\d+)\+(\d+)') {
  $new = "version: $($Matches[1])+$([int]$Matches[2] + 1)"; $txt = $txt -replace 'version:\s*\d+\.\d+\.\d+\+\d+', $new; Set-Content $pub $txt -NoNewline
}
$null = (Get-Content $pub -Raw) -match 'version:\s*(\d+\.\d+\.\d+)\+(\d+)'
$name = $Matches[1]; $code = [int]$Matches[2]
Push-Location "$root\android_app"; flutter build apk --release --split-per-abi; Pop-Location
New-Item -ItemType Directory -Force "$root\dist\app" | Out-Null
Copy-Item "$root\android_app\build\app\outputs\flutter-apk\app-arm64-v8a-release.apk" "$root\dist\app\PocketDesk.apk" -Force
@{ versionCode = $code; versionName = $name; url = "/app/PocketDesk.apk"; notes = $Notes } | ConvertTo-Json | Set-Content "$root\dist\app\version.json"
Write-Host "Published PocketDesk $name (build $code) -> dist\app. Phones update from the app menu or automatically on next open."
