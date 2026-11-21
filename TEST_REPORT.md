# Test Report (2026-11-21, Windows 11, this dev PC, single 1920×1080 monitor, no Android device)

## Automated results
| Suite | Command | Result |
|---|---|---|
| Signaling (10) | `cd signaling; python -m pytest -q` | 10 passed — pairing, single-use code, rate limit, auth, relay, ICE/TURN cred, revocation, offline, register key, hashed secrets |
| Agent unit (8) | `cd agent; python -m pytest tests/test_units.py` | 8 passed — HKDF RFC5869 vector, code parse, MAC fingerprint binding, coordinate mapping (multi-monitor offsets, corners, roundtrip), input validation, key release, unicode text |
| **Agent REAL integration (2)** | `cd agent; python -m pytest tests/test_integration_real.py -s` | 2 passed. Real uvicorn signaling + real Agent + real aiortc phone peer (`tests/device_peer.py`, same protocol as the app). Verified: pairing; DPAPI-at-rest; E2E MAC handshake; **real VP8 video of the actual desktop** (mean abs diff 6.1/255 vs fresh screenshot); cursor positions via normalized coords within 2 px (3 targets); relative move; real Shift key state via GetAsyncKeyState; held-key release on disconnect; bad input rejected; ping/pong; runtime cfg; clipboard both directions (Unicode); session end; unauthorized offers (bad MAC, stale ts, no key) rejected; revocation. |
| Flutter unit (8) | `cd mobile; flutter test` | 8 passed — HKDF vector, pairing-code parse, **cross-language MAC vectors from Python**, letterbox/zoom/pan mapping, clampPan |
| Flutter static | `flutter analyze` | no issues |
| Android build | `flutter build apk --release` | success (≈84 MB, includes all ABIs) |
| Windows agent package | `tools\build_agent.ps1`, then `PocketDeskAgent.exe selftest` | exe built (62 MB zip); selftest PASS: DXGI capture of real screen, VP8 encoder, DPAPI, aiortc |

## Added after first report (web client, relay, UX)
| Suite | Result |
|---|---|
| Agent (12) incl. REAL relay test (`tests/test_relay_real.py`) | 12 passed (one flaky failure seen once when a human moved the real mouse during the cursor check; rerun green) |
| Server (11) incl. static web client/PWA routes | 11 passed |
| **Real browser E2E** `python tools/e2e_web/run.py` (headless Chrome → real server → real agent → real PC cursor) | PASS for both **direct WebRTC** and **encrypted relay**: pairing from QR link, video, click lands at centre, **rotated view maps to the correct PC position**, zoom, sign-out |
Verified by the user on a real phone (manual): QR scan → pairing → relay session worked ("great job its working").
Not verified: pinch gesture / rotate on real touch hardware, PWA install, in-page QR scanner (BarcodeDetector), lock-screen message with a real lock, Vercel/Render deployment.

## Performance (tools/perf.py; agent as separate process; loopback; mostly static desktop)
| Quality | recv fps | size | agent bitrate | agent CPU* | agent RSS |
|---|---|---|---|---|---|
| low | 12.1 | 960×540 | 0.44 Mbit/s | 2.2% (≈0.6 core) | 175 MB |
| medium | 20.1 | 1280×720 | 0.62 Mbit/s | 3.1% (≈0.9 core) | 189 MB |
| high | 28.2 | 1920×1080 | 3.14 Mbit/s | 5.7% (≈1.6 core) | 252 MB |
\*percent of all 28 logical cores on this machine. Software VP8 (libvpx) is used; hardware encoding is not implemented (CPU cost is the main limitation on weak PCs — use Low/Medium). Bitrate rises with screen motion (static desktop shown). End-to-end latency over a real WAN not measured; loopback RTT only.

## NOT verified (implemented but untested here)
- **The Flutter app running on a device/emulator** (none available; `flutter test --platform chrome` hung even for a trivial test in this environment, so `mobile/test/e2e_web_test.dart` + `tools/e2e_flutter_web.py` — a harness that runs the real Dart client against the real agent in Chrome — could not be executed). The Dart protocol code is therefore verified only by analysis, unit tests and cross-language crypto vectors; the identical protocol is exercised end-to-end by the Python peer. Expect to fix small runtime issues on first real-device run (e.g. flutter_webrtc API behaviour, gesture tuning, soft-keyboard handling).
- Touch gestures, keyboard bar, zoom/pan UX on real hardware.
- STUN/TURN and any cross-network connection; network switching/reconnect; TLS deployment; Docker compose files.
- Multi-monitor selection (code + coordinate math tested; only one monitor present).
- Agent Tk UI/banner (not screenshot-tested), autostart registry command, install/uninstall scripts.
- Remote lock (deliberately not triggered).
- Idle timeout / 12 h expiry paths.
