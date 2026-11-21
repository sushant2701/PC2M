# PocketDesk — project rules

Personal remote desktop: Windows agent (Python) + Android client (Flutter) + signaling service (FastAPI) + WebRTC.
Resume order: this file → PROJECT_STATUS.md → TASKS.md → DECISIONS.md (if relevant) → relevant source only.

## Layout
- `agent/` Windows agent (`pocketdesk_agent`), `signaling/` FastAPI service, `mobile/` Flutter app, `tools/` real test peer & build scripts, `docs/` guides.

## Hard rules
- Change only what the task needs; never touch unrelated files/projects/user data. Keep changes targeted and reversible.
- No mocks presented as complete features. Mocks only in tests where real env is unavailable, labelled as such in TEST_REPORT.md.
- Never silently disable/skip tests to pass builds. Never claim a feature works unless verified; list unverified items.
- No hardcoded secrets, private keys, passwords. Secrets via env/DPAPI/secure storage.
- No unauthenticated remote control, no hidden/stealth access, no keylogging, no security bypass, no insecure auth.
- Remote session must always be visible on the PC (indicator + disconnect). Startup-on-boot only by explicit user opt-in.
- Do not disable/modify antivirus, Defender, firewall or other Windows security settings. No destructive ops without confirmation.
- Don't install suspicious/unmaintained dependencies; check licences (permissive/LGPL OK).
- Bounded debugging: after 3 failed attempts at one problem, document in DECISIONS.md/TASKS.md, change strategy, continue elsewhere.
- Update TASKS.md / PROJECT_STATUS.md / CHANGELOG.md at each milestone. Commit locally at stable milestones; never force-push.

## Skills (.claude/skills/*) — use the one matching the domain
architecture, windows-agent, flutter-mobile, webrtc-networking, security-review, testing, token-efficiency.

## Commands
- Signaling tests: `cd signaling; python -m pytest -q`
- Agent tests: `cd agent; python -m pytest -q`
- Integration (real desktop): `cd agent; python -m pytest tests/test_integration_real.py -q`
- Mobile: `cd mobile; flutter analyze; flutter test; flutter build apk`
