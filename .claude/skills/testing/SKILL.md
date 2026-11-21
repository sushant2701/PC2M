---
name: testing
description: Test strategy and commands for PocketDesk. Use when adding/running tests or updating TEST_REPORT.md.
---
- Unit: crypto vectors, coordinate mapping, input message validation, db/auth/rate limit (pytest; flutter test).
- Signaling: FastAPI TestClient + real WS flows.
- Real integration: `agent/tests/test_integration_real.py` starts real signaling + real agent + real aiortc "device" peer, verifies decoded video frames from the actual desktop and that a remote mouse move changes the real cursor. Mark simulated parts honestly in TEST_REPORT.md.
- Targeted runs first (`pytest path::test -q`), full suites at milestones. Never delete/skip a failing test to go green.
