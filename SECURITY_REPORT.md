# Security Report (2026-11-21) — self-review, not an independent audit

## Controls implemented (and how verified)
| Control | Implementation | Verified by |
|---|---|---|
| No unauthenticated control | Offer must carry HMAC(pair_key, session, device, ts, DTLS fingerprint); agent verifies with locally stored key before creating a peer connection or capturing the screen | `test_unauthorized_offers_are_rejected` (wrong MAC, stale ts, attacker with valid device token but no key) |
| Untrusted signaling server | Pair secret (80 bit) never sent to server; MACs bind DTLS fingerprints both ways (phone verifies answer) | crypto unit tests + cross-language vectors (Dart ⇔ Python) |
| Pairing | Single-use 5-min lookup code, per-IP (10/min) + global (100/min) claim limits, agent verifies claim proof, revokes on bad proof, requires agent online | signaling tests |
| Token storage | Server stores SHA-256 of agent secrets/device tokens, constant-time compare; agent config DPAPI-encrypted (user scope); phone uses Android Keystore-backed flutter_secure_storage | test (secret absent from file / DB) |
| Revocation | Server marks revoked, closes WS, notifies agent; agent deletes key and ends live session; revoked token re-checked on every WS message | `test_revocation_blocks_and_closes`, agent revoke test |
| Replay | session_id single-use (2000 remembered) + ±120 s timestamp window | agent integration test (stale ts) |
| Input authorization/validation | Control channel exists only after authenticated session; every message type/range/key-name validated; unknown keys rejected; held keys/buttons released on disconnect | unit + real tests |
| Session limits | idle 30 s timeout (phone pings every 2 s), 12 h hard cap, one session at a time (new authenticated offer replaces) | code; idle/expiry paths not exercised in tests |
| Transport | DTLS-SRTP/DTLS data channel; release app and agent require https/wss (http only for localhost/LAN in agent; debug builds in app) | code review; Android release manifest has no cleartext flag |
| Visibility | Red always-on-top banner + Disconnect for the whole session; no stealth mode; autostart is opt-in; per-user install, no service | manual design; UI not screenshot-tested |
| Logging | Security events logged (pair, offer rejected, session start/end, revoke); no secrets/SDP at info level | code review |
| Rate limiting | registration 10/h/IP, claim, auth failures, pair-code creation | signaling tests (claim) |

## Known risks / limitations
1. **A paired phone is full control of the PC while a session runs.** Lost phone → revoke immediately. Consider a screen lock on the phone; the app has no extra PIN yet.
2. Local malware running as the same Windows user can read the DPAPI blob (inherent to user-scope DPAPI).
3. Signaling operator can see metadata (names, online status, timing) and can deny service, but cannot view/control the PC.
4. Pair-code lookup is 30 bit; protection is rate limit + TTL + the 80-bit secret requirement. An attacker winning the lookup race only causes pairing failure for the legitimate user (DoS), and the agent rejects the attacker's proof.
5. TURN uses shared-secret ephemeral credentials; coturn must be configured with the same secret and private-range deny list (provided in the compose file).
6. Release APK in this repo is signed with a debug key; use your own keystore for distribution.
7. Remote lock only; remote shutdown/restart intentionally NOT implemented.
8. Dependencies are from PyPI/pub.dev (aiortc BSD, dxcam MIT, mss MIT, FastAPI MIT, flutter_webrtc MIT); no `pip-audit`/`dart pub audit` run was performed.
9. Not tested: TURN relay path, TLS termination, WS brute force behaviour behind a proxy (`TRUST_PROXY` must only be set behind a trusted proxy).
