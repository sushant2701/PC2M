# PocketDesk

Control your Windows PC from your Android phone over the internet (different networks), seeing and driving the real desktop.

- `agent/` Windows agent (Python): DXGI screen capture → VP8 WebRTC video, SendInput mouse/keyboard, clipboard, lock. Tk window + red "REMOTE SESSION ACTIVE" banner with Disconnect.
- `signaling/` FastAPI service: pairing, presence, SDP relay, TURN credentials. Never sees video or the pairing secret.
- `mobile/` Flutter Android app: pairing, PC list, viewer, touch/trackpad, keyboard, zoom/pan, settings.
- `tools/` build scripts, real test peer harnesses, perf measurement. `docs/` guides.

Start here: [docs/INSTALL.md](docs/INSTALL.md) → [docs/NETWORKING.md](docs/NETWORKING.md) → [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
Status & honesty: [PROJECT_STATUS.md](PROJECT_STATUS.md), [TEST_REPORT.md](TEST_REPORT.md), [SECURITY_REPORT.md](SECURITY_REPORT.md).
