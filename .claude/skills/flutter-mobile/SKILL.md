---
name: flutter-mobile
description: Flutter Android client work (UI, touch→mouse, WebRTC client, storage). Use for anything under mobile/.
---
- Packages: flutter_webrtc, web_socket_channel, http, crypto, flutter_secure_storage. Keep deps minimal.
- Pairing secrets/tokens only in flutter_secure_storage. Release builds https/wss only; cleartext only in debug manifest.
- Remote view: RTCVideoView in InteractiveViewer-like transform; touch coordinates → normalized (0..1) of the displayed video rect (letterbox aware). Unit-test the mapping.
- Modes: touch (direct), trackpad (relative). Gestures: tap=left, two-finger tap=right, long-press=right/drag, two-finger scroll, pinch zoom, 3-finger/double-tap toggles UI.
- Minimal chrome while connected; auto-hide toolbar. Show quality/RTT indicator.
- Run `flutter analyze` and `flutter test` before marking tasks done.
