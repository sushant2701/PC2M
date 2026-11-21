# Install, pair, use

## 0. What you need
1. **A signaling server reachable from both networks** (small VPS, ~USD 4/mo, or any always-on machine with HTTPS). See NETWORKING.md. For a same-LAN trial you can run it on the PC: `tools\run_signaling.ps1` (http, LAN only).
2. The Windows PC (Windows 10/11, user logged in and unlocked) and an Android phone (7.0+).

## 1. Signaling server (production)
```
cd signaling\deploy
copy .env.example .env      # edit DOMAIN, TURN_SECRET (long random), REGISTER_KEY
docker compose up -d --build
```
Open ports 80, 443/tcp, 3478/udp+tcp, 49160-49200/udp. Caddy gets the HTTPS certificate automatically.
Server URL = `https://<DOMAIN>`.

## 2. Windows agent
Build (or use `dist\PocketDeskAgent-win64.zip`): `powershell tools\build_agent.ps1`
Install for the current user (no admin): unzip, run `powershell .\install_agent.ps1` (add `-Autostart` ONLY if you want it to start at logon).
Start **PocketDesk Agent** from the Start menu → *Set server URL…* → paste `https://<DOMAIN>` → restart the agent. Status shows "Online".
CLI alternative: `PocketDeskAgent.exe config --server https://<DOMAIN> --register-key <KEY>`.
Remove: `.\uninstall_agent.ps1` (`-RemoveData` also deletes keys/logs in %APPDATA%\PocketDesk).

## 3. Android app
Install `dist\PocketDesk.apk` (enable "install unknown apps" for your file manager) or build: `cd mobile; flutter build apk --release`.
LAN trial against `tools\run_signaling.ps1` (plain http) needs a **debug** build: `flutter build apk --debug` — release builds refuse http.
The bundled release APK is signed with the Flutter **debug key** — create your own keystore before sharing it.

## 4. Pair
1. PC: **Pair a new phone** → code like `ABCDEF-GHIJ-KLMN-OPQR-STUV` (valid 5 min, single use).
2. Phone: **Pair PC** → server address + code (paste button) → Pair. The PC shows a confirmation.
The code is part-secret: 80 of its bits never reach the server and key the end-to-end authentication, so type/paste all of it.

## 5. Use
Tap the PC. Top handle toggles the toolbar. Gestures: tap=click, long-press=right click, drag=drag, two-finger drag=scroll, two-finger tap=right click, pinch=zoom, hand icon=pan zoomed view, mouse icon=trackpad mode. Keyboard icon opens the soft keyboard; the ⌘ icon shows Ctrl/Alt/Shift/Win, arrows, F-keys and shortcuts. Quality menu: low/medium/high. The red ✕ disconnects.
On the PC a red banner is shown for the entire session; **Disconnect** there ends it immediately. Revoke a phone from the agent window ("Revoke selected") or by removing the PC in the app.

## Development
```
cd signaling; python -m pytest -q          # server tests
cd agent;     python -m pytest tests -q    # unit + REAL integration (moves your cursor briefly)
cd mobile;    flutter analyze; flutter test; flutter build apk
python tools\perf.py                       # measurements
```
