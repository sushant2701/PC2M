# Decisions
- **D1 Agent in Python, not Rust** (2026-11-21): no Rust/MSVC toolchain and no admin; installing multi-GB build tools not justified. Python 3.11 + aiortc (BSD) + dxcam (MIT) + mss (MIT) are maintained, pip-only, and can be packaged with PyInstaller. Tradeoff: higher CPU for software encode; mitigated by downscale + fps cap. Revisit Rust if perf data demands.
- **D2 WebRTC via aiortc / flutter_webrtc**: established implementations; no custom protocol.
- **D3 Non-trickle ICE**: simplifies signaling; slightly slower connect.
- **D4 E2E pair key**: signaling server untrusted (see ARCHITECTURE.md).
- **D5 VP8 video**: ubiquitous, software-encodable via PyAV; H264 optional.
- **D6 SQLite for signaling**: tiny metadata, zero ops.
- **D7 TURN = self-hosted coturn on the same small VPS** (REST ephemeral creds); no paid resources created by me.
