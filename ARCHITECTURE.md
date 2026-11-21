# PocketDesk Architecture

```
 Android (Flutter) ──HTTPS/WSS──► Signaling (FastAPI) ◄──HTTPS/WSS── Windows Agent (Python)
        │                                                                    │
        └────────── WebRTC (DTLS-SRTP video + DTLS data channel) ────────────┘
                    direct via STUN, else relayed by TURN (coturn)
```

## Components
- **Agent** (`agent/`): captures desktop (DXGI via dxcam, mss fallback), encodes (VP8 via aiortc/PyAV), streams, injects input (SendInput), tk control window + session indicator, DPAPI-protected storage.
- **Signaling** (`signaling/`): registers agents, pairing codes, device tokens, presence, SDP relay, ICE/TURN credentials, revocation. SQLite; stores only hashes + names.
- **Mobile** (`mobile/`): pairing, PC list, viewer, touch/trackpad, keyboard, settings.

## Protocol (v1)
### Pairing
1. Agent generates `lookup` (6 base32 chars) and `secret` (16 base32 chars = 80 bit). Displays `LLLLLL-SSSS-SSSS-SSSS-SSSS`. Only `lookup` is sent to server (`POST /api/agents/pair-code`, TTL 300 s, single use).
2. `pair_key = HKDF-SHA256(ikm=secret_bytes(10), salt="pocketdesk-pair-v1", info="pair-key", 32)`.
3. Phone: `POST /api/pair/claim {code: lookup, device_name, proof}` with `proof = hex(HMAC(pair_key, "pd1|claim|"+lookup+"|"+device_name))`. Server returns `device_id`, `device_token`, `agent_id`, `agent_name`; forwards `paired{device_id, device_name, proof, lookup}` to the agent, which verifies proof and stores `{device_id, name, pair_key}`; bad proof ⇒ agent asks server to revoke.
### Session
- Phone → server (WS, authenticated by device token): `offer{agent_id, session_id, ts, sdp, mac}`; `mac = hex(HMAC(pair_key, "pd1|offer|"+session_id+"|"+device_id+"|"+ts+"|"+fp))`, `fp` = first `a=fingerprint:` value, lower-case.
- Agent verifies: device known, `|now-ts|<=120s`, session_id unused, MAC valid, then answers `answer{device_id, session_id, sdp, mac}` (`"pd1|answer|"` variant with agent's fingerprint). Phone verifies the answer MAC. ⇒ a malicious signaling server cannot MITM DTLS.
- Non-trickle ICE. `bye{session_id}` ends. ICE servers (STUN + TURN REST creds) delivered in `ready`.
### Data channel `control` (JSON, reliable, ordered; agent→phone `info`, phone→agent input)
- `{t:"mm",x,y}` absolute move (0..1 of selected monitor); `{t:"mr",dx,dy}` relative px move
- `{t:"mb",b:"left|right|middle",d:true|false}` button; `{t:"ws",dx,dy}` wheel (notches, float)
- `{t:"k",c:"<code>",d:bool}` key by name (e.g. `KeyA`, `Enter`, `ControlLeft`); `{t:"tx",s:"text"}` unicode text
- `{t:"cfg",maxw,fps,monitor,quality}` stream settings; `{t:"ping",n}` → `{t:"pong",n}`; `{t:"bye"}`
- agent→phone: `{t:"info",monitors:[{i,w,h}],monitor,w,h}`, `{t:"cur",x,y}` cursor pos (0..1), `{t:"stats",fps,kbps,w,h}`
- Optional (phase 7): `{t:"clip",s}`, `{t:"pw",a:"lock"}` confirmed on PC.

## Threat model (summary)
| Threat | Mitigation |
|---|---|
| Stranger reaches signaling and controls PC | needs device token AND agent-verified MAC from pair_key |
| Malicious/compromised signaling server | E2E MAC bound to DTLS fingerprints; server never knows secret |
| Pair-code brute force | 30-bit lookup, 5-min TTL, single use, per-IP and per-code attempt limits; 80-bit secret needed anyway |
| Stolen phone | agent-side/phone-side revoke; session TTL; visible indicator |
| Replay | session_id single-use + ts window |
| Local malware reading creds | DPAPI (user-scope) — same as any user-level app; documented limitation |
| Hidden access | indicator window always shown during session; user-installed, user-run |
