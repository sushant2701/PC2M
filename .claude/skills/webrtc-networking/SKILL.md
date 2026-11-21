---
name: webrtc-networking
description: Signaling, ICE/STUN/TURN, reconnection and media/data-channel behaviour. Use for networking changes.
---
- Non-trickle ICE: wait for gathering complete before sending offer/answer (simple signaling).
- Data channel `control` ordered+reliable for input/settings; video via sendonly track from agent (VP8/H264).
- ICE servers come from signaling `ready` message (STUN list + ephemeral coturn REST credentials). TURN secret only on server.
- Reconnect: phone retries signaling with backoff and re-offers on ICE failure; agent drops stale sessions after timeout.
- Direct P2P can fail behind symmetric NAT/CGNAT → TURN (coturn, TLS 443/5349) required; document in docs/NETWORKING.md.
- Never log SDP bodies at info level.
