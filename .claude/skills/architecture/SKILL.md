---
name: architecture
description: PocketDesk architecture and protocol rules. Use when changing component boundaries, protocol messages, pairing crypto or data flow.
---
- Components: agent (PC) ⇄ signaling (FastAPI, WS+REST) ⇄ phone. Media/input go peer-to-peer over WebRTC (STUN, TURN fallback); signaling never sees media.
- Protocol is specified in ARCHITECTURE.md ("Protocol"). Change spec first, then agent + mobile + tests together.
- Signaling is untrusted for confidentiality/authorization: offers/answers carry HMAC bound to DTLS fingerprint with pair key derived from a secret the server never sees.
- Input uses normalized (0..1) coordinates relative to the selected monitor; the agent maps to virtual-desktop pixels.
- Record choices in DECISIONS.md (short ADR style). Keep components simple; no new deps without need.
