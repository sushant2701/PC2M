---
name: windows-agent
description: Work on the Windows agent (capture, encode, input, session, UI, storage). Use for anything under agent/.
---
- Python 3.11, aiortc for WebRTC, dxcam (DXGI Desktop Duplication) with mss fallback, ctypes SendInput for input. Optional deps must degrade gracefully.
- Capture runs off the event loop thread; never block asyncio. Downscale to max width setting before encode; repeat last frame when no new frame.
- Input: validate every message schema/ranges; only accept after session authorized; release held keys/buttons on disconnect.
- Limits to document, not hack: elevated windows/UAC/lock screen can't be controlled from a user-level process.
- Secrets in `%APPDATA%\PocketDesk` protected with DPAPI. Log security events (pair, connect, reject, revoke) without secrets.
- Visible indicator while a session is active (tk window, always-on-top) with a Disconnect button. Headless mode must still log.
