---
name: security-review
description: Security checklist for auth, pairing, tokens, crypto, rate limiting, input authorization. Use before finishing any security-relevant change.
---
Checklist: no endpoint allows control without (a) server-authenticated device AND (b) valid pair-key MAC verified by the agent; tokens stored hashed (server) / DPAPI or secure storage (clients); constant-time compares; pair codes single-use, 5 min TTL, attempt-limited; revocation closes live sessions; session TTL enforced; replay (session_id, ts window) rejected; input messages schema-validated; logs contain no secrets; TLS required outside localhost; dependencies from PyPI/pub.dev only. Update SECURITY_REPORT.md.
