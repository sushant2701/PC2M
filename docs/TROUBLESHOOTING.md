# Troubleshooting
Agent log: `%APPDATA%\PocketDesk\agent.log` (security events tagged `pocketdesk.security`). Run `PocketDeskAgent.exe selftest --out r.txt` to verify capture/encoder/DPAPI.

| Symptom | Cause / fix |
|---|---|
| App: "PC is offline" | Agent not running, PC asleep/off, or agent can't reach the server (check agent window status & URL). |
| Pair: "Code is invalid or expired" | 5-minute single-use code; generate a new one. Entered wrong server? |
| Pair: "Too many attempts" | Rate limit; wait 1 minute. |
| Stuck at "Connecting…" then fails | Direct path blocked and no TURN. Configure TURN (NETWORKING.md). |
| "Security check failed: the PC could not be verified" | Answer MAC mismatch: wrong/old pairing or a tampering server. Remove the PC and re-pair. |
| Black/blank screen | PC locked, on UAC prompt, or on Ctrl+Alt+Del screen — not capturable/controllable by a user-level app. Unlock locally. |
| Can't click in an "Administrator" app | Windows blocks input to elevated windows from a normal process. Run the agent elevated *only if you accept the risk* (not recommended/supported by the installer). |
| Laggy / low quality | Use Low quality; lower the PC resolution; check RTT/fps in toolbar. High quality needs ~3 Mbit/s and ~1.6 CPU cores on the PC. |
| Keys stuck | They are released automatically on disconnect; tap the key again to release. |
| Remote text typing odd on non-US layouts | Text is sent as Unicode characters; shortcuts use US key positions. |
| Revoked | The PC owner revoked the phone; remove and re-pair. |
