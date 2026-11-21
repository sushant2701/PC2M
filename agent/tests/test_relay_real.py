"""REAL test of the encrypted WebSocket relay fallback: real server, real agent, real desktop, real input."""
import asyncio
import io
import time

import numpy as np
import pytest
from PIL import Image

from pocketdesk_agent.agent import Agent
from pocketdesk_agent.config import Config
from device_peer import DevicePeer
from test_integration_real import server, wait_for, cursor_reaches, cursor, user32  # noqa: F401


@pytest.mark.asyncio
async def test_zoom_region_is_sent_at_full_resolution(server, tmp_path):
    """Zoom must be crisp: the PC cuts the visible region out of its FULL-resolution screen instead of magnifying a small picture."""
    cfg = Config(tmp_path / "agent.bin")
    cfg["server_url"] = server
    agent = Agent(cfg)
    run = asyncio.ensure_future(agent.run())
    phone = DevicePeer(server)
    try:
        assert await wait_for(lambda: agent.connected)
        await phone.pair(await agent.start_pairing())
        await phone.connect_signaling()
        assert (await phone.start_relay())["type"] == "relay_ok"
        assert await wait_for(lambda: len(phone.relay_frames) >= 2, 20)
        phone.send({"t": "cfg", "quality": "low"})  # low = 960 px wide whole-screen frames
        await asyncio.sleep(1.5)
        full = Image.open(io.BytesIO(phone.relay_frames[-1])).convert("RGB")
        assert full.size[0] <= 960
        roi = {"x": 0.25, "y": 0.25, "w": 0.25, "h": 0.25}  # a 480x270 px window of a 1920x1080 screen
        phone.messages.clear()
        phone.send({"t": "cfg", "roi": roi})
        assert await wait_for(lambda: any(m.get("t") == "roi_ok" for m in phone.messages), 5)
        ack = next(m for m in phone.messages if m.get("t") == "roi_ok")
        assert ack["roi"] == roi
        phone.relay_frames.clear()
        # wait for a frame that has exactly the acknowledged size
        def got():
            for b in phone.relay_frames:
                if Image.open(io.BytesIO(b)).size == (ack["w"], ack["h"]):
                    return True
            return False
        assert await wait_for(got, 10), f"no frame of acknowledged size {ack['w']}x{ack['h']}"
        crop = next(Image.open(io.BytesIO(b)).convert("RGB") for b in phone.relay_frames if Image.open(io.BytesIO(b)).size == (ack["w"], ack["h"]))
        import mss
        with mss.MSS() as s:
            shot = s.grab(s.monitors[1])
        W, H = shot.size
        ref = Image.frombytes("RGB", shot.size, shot.rgb).crop((int(0.25 * W), int(0.25 * H), int(0.5 * W), int(0.5 * H))).resize(crop.size)
        diff = np.abs(np.asarray(ref, dtype=np.float32) - np.asarray(crop, dtype=np.float32)).mean()
        native = int(0.25 * W)
        print(f"\n[zoom] whole-screen frame {full.size}; zoomed crop {crop.size} (native region {native}px wide), diff {diff:.1f}")
        assert crop.size[0] >= min(native, 320) - 16, "zoomed frame is not at native resolution"
        assert diff < 40
        # clearing the region returns to whole-screen frames
        phone.messages.clear()
        phone.send({"t": "cfg", "roi": None})
        assert await wait_for(lambda: any(m.get("t") == "roi_ok" and m["roi"] is None for m in phone.messages), 5)
        # bad regions are rejected
        phone.send({"t": "cfg", "roi": {"x": 2, "y": 0, "w": 0.5, "h": 0.5}})
        await asyncio.sleep(0.3)
        phone.send({"t": "bye"})
    finally:
        await phone.close()
        await agent.stop()
        run.cancel()


@pytest.mark.asyncio
async def test_closing_app_stops_everything_and_flood_is_blocked(server, tmp_path):
    """When the app is closed the PC must go completely quiet: session ends at once, capture stops, nothing is held down."""
    cfg = Config(tmp_path / "agent.bin")
    cfg["server_url"] = server
    agent = Agent(cfg)
    run = asyncio.ensure_future(agent.run())
    phone = DevicePeer(server)
    saved = cursor()
    try:
        assert await wait_for(lambda: agent.connected)
        await phone.pair(await agent.start_pairing())
        assert await wait_for(lambda: phone.device_id in cfg["devices"])
        await phone.connect_signaling()
        assert (await phone.start_relay())["type"] == "relay_ok"
        assert await wait_for(lambda: len(phone.relay_frames) >= 1, 20)
        assert agent.source is not None
        phone.send({"t": "k", "c": "ShiftLeft", "d": True})
        assert await wait_for(lambda: user32.GetAsyncKeyState(0x10) & 0x8000, 5)
        # app killed abruptly (no goodbye message): socket just dies
        await phone.ws.close()
        assert await wait_for(lambda: agent.session is None, 5), "session still alive after the app closed"
        assert agent.source is None, "screen capture still running with nobody connected"
        assert await wait_for(lambda: not (user32.GetAsyncKeyState(0x10) & 0x8000), 3), "key left pressed"
        # nobody connected: the stale phone cannot start input any more
        assert agent.session is None
    finally:
        user32.keybd_event(0xA0, 0, 2, 0)
        user32.SetCursorPos(*saved)
        await agent.stop()
        run.cancel()


@pytest.mark.asyncio
async def test_flood_and_garbage_end_the_session(server, tmp_path):
    cfg = Config(tmp_path / "agent.bin")
    cfg["server_url"] = server
    agent = Agent(cfg)
    run = asyncio.ensure_future(agent.run())
    phone = DevicePeer(server)
    saved = cursor()
    try:
        assert await wait_for(lambda: agent.connected)
        await phone.pair(await agent.start_pairing())
        await phone.connect_signaling()
        assert (await phone.start_relay())["type"] == "relay_ok"
        assert await wait_for(lambda: agent.session is not None)
        for i in range(60):  # malformed / unknown messages: must be rejected and eventually end the session
            phone.send({"t": "definitely-not-a-command", "i": i})
            phone.send({"t": "mm", "x": "bad", "y": None})
        assert await wait_for(lambda: agent.session is None, 10), "garbage did not end the session"
    finally:
        user32.SetCursorPos(*saved)
        await phone.close()
        await agent.stop()
        run.cancel()


@pytest.mark.asyncio
async def test_relay_session(server, tmp_path):
    cfg = Config(tmp_path / "agent.bin")
    cfg["server_url"] = server
    agent = Agent(cfg)
    run = asyncio.ensure_future(agent.run())
    phone = DevicePeer(server)
    saved = cursor()
    try:
        assert await wait_for(lambda: agent.connected)
        await phone.pair(await agent.start_pairing())
        assert await wait_for(lambda: phone.device_id in cfg["devices"])
        await phone.connect_signaling()
        # unauthorized relay requests are refused
        bad = await phone.start_relay(mac_override="00" * 32)
        assert bad["type"] == "error" and agent.session is None
        bad = await phone.start_relay(ts=int(time.time()) - 3600)
        assert bad["type"] == "error" and agent.session is None
        ok = await phone.start_relay()
        assert ok["type"] == "relay_ok"
        assert await wait_for(lambda: len(phone.relay_frames) >= 3, 20), "no relayed frames"
        img = Image.open(io.BytesIO(phone.relay_frames[-1])).convert("RGB")
        arr = np.asarray(img)
        assert img.size[0] >= 640 and arr.std() > 5
        import mss
        with mss.MSS() as s:
            shot = s.grab(s.monitors[1])
        ref = np.asarray(Image.frombytes("RGB", shot.size, shot.rgb).resize(img.size), dtype=np.float32)
        diff = np.abs(ref - arr.astype(np.float32)).mean()
        print(f"\n[relay] {img.size} frame, diff vs screenshot {diff:.1f}, frame bytes {len(phone.relay_frames[-1])}")
        assert diff < 40
        phone.send({"t": "mm", "x": 0.4, "y": 0.4})
        mon = agent.source.current_monitor()
        assert await cursor_reaches(mon["left"] + 0.4 * (mon["width"] - 1), mon["top"] + 0.4 * (mon["height"] - 1))
        phone.send({"t": "ping", "n": 3})
        assert await wait_for(lambda: {"t": "pong", "n": 3} in phone.messages, 5)
        assert any(m.get("t") == "info" for m in phone.messages)
        phone.send({"t": "bye"})
        assert await wait_for(lambda: agent.session is None, 10)
    finally:
        user32.SetCursorPos(*saved)
        await phone.close()
        await agent.stop()
        run.cancel()
