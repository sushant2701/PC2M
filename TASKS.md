# TASKS (✔ = implemented and verified as stated in TEST_REPORT.md)
## Done & verified
- [x] P0 Environment audit — ENVIRONMENT_REPORT.md
- [x] P1 CLAUDE.md, 7 skills, ARCHITECTURE (protocol + threat model), DECISIONS
- [x] Signaling service (pairing, presence, relay, TURN creds, revocation, rate limits) — 10 tests
- [x] Agent: crypto, DPAPI config, DXGI/GDI capture, VP8 WebRTC, SendInput mouse/keyboard/unicode, clipboard, lock, session lifecycle, CLI, Tk UI + banner — unit + REAL integration tests
- [x] Real desktop streaming + real input verified on this PC (loopback)
- [x] Perf measurements (TEST_REPORT.md)
- [x] Windows package: PyInstaller exe + zip + per-user install/uninstall scripts; exe selftest PASS
- [x] Flutter app implemented; analyze clean; unit tests; release APK builds
- [x] Docs: README, INSTALL, NETWORKING, TROUBLESHOOTING, SECURITY_REPORT, TEST_REPORT
## Unverified (implemented, needs real-world check)
- [ ] Flutter app on a real Android device (viewer, gestures, keyboard)
- [ ] Cross-network + TURN; TLS deployment; network-change reconnect
- [ ] Multi-monitor with >1 display; Tk banner appearance
## Not implemented (scope decision)
- File transfer, audio, Wake-on-LAN, remote restart/shutdown, hardware (NVENC) encoding, adaptive resolution beyond REMB bitrate adaptation, app-level PIN/biometric lock, Rust agent (see DECISIONS D1)
## Known issues
- Elevated windows / UAC / lock screen cannot be controlled (Windows limitation for user-level process)
- Release APK signed with debug key
- `flutter test --platform chrome` hangs in this environment (tooling), e2e_web_test not executed
- Agent holds frames as shared av.VideoFrame; pts reassigned per send (low-risk race at very high fps)
