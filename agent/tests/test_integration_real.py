"""REAL integration test: real signaling server (uvicorn), real agent, real aiortc phone peer,
real desktop capture, real SendInput. Same machine, loopback network (cross-network NOT covered)."""
import asyncio
import ctypes
import socket
import sys
import threading
import time
from ctypes import wintypes

import numpy as np
import pytest
import uvicorn

from pocketdesk_agent.agent import Agent
from pocketdesk_agent.config import Config
from pocketdesk_signaling.app import create_app
from device_peer import DevicePeer

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
user32 = ctypes.windll.user32


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def cursor():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


@pytest.fixture
def server(tmp_path):
    port = free_port()
    app = create_app(str(tmp_path / "s.db"), stun_urls=[])
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(5)


async def wait_for(cond, timeout=15, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        await asyncio.sleep(step)
    return False


async def cursor_reaches(px, py, tol=2, timeout=5):
    """Real machine may have a human moving the mouse: sample fast so the injected position is observed."""
    return await wait_for(lambda: abs(cursor()[0] - px) <= tol and abs(cursor()[1] - py) <= tol, timeout, 0.002)


@pytest.mark.asyncio
async def test_full_remote_session(server, tmp_path):
    cfg = Config(tmp_path / "agent.bin")
    cfg["server_url"] = server
    cfg["name"] = "TestPC"
    events = []
    agent = Agent(cfg, lambda k, d=None: events.append((k, d)))
    run = asyncio.ensure_future(agent.run())
    phone = DevicePeer(server)
    saved_cursor = cursor()
    try:
        assert await wait_for(lambda: agent.connected), "agent did not connect to signaling"
        code = await agent.start_pairing()
        await phone.pair(code)
        assert await wait_for(lambda: phone.device_id in cfg["devices"]), "agent did not record pairing"
        # key at rest is DPAPI-encrypted, never plaintext
        raw = (tmp_path / "agent.bin").read_bytes()
        assert cfg["agent_secret"].encode() not in raw

        await phone.connect_signaling()
        ans = await phone.start_session()
        assert ans["type"] == "answer"

        # --- real video of the real desktop ---
        frames = []
        for _ in range(15):
            frames.append(await asyncio.wait_for(phone.video_frames.get(), 20))
        f = frames[-1]
        img = f.to_ndarray(format="rgb24")
        assert img.shape[1] >= 640 and img.std() > 5, "frame looks blank"
        import mss
        with mss.MSS() as s:
            shot = s.grab(s.monitors[1])
        from PIL import Image
        ref = np.asarray(Image.frombytes("RGB", shot.size, shot.rgb).resize((img.shape[1], img.shape[0])), dtype=np.float32)
        diff = np.abs(ref - img.astype(np.float32)).mean()
        print(f"\n[real] received {img.shape[1]}x{img.shape[0]} frame; mean abs diff vs fresh screenshot = {diff:.1f}")
        assert diff < 40, "received video does not match the real desktop"
        assert await wait_for(lambda: any(m.get("t") == "info" for m in phone.messages))
        assert await wait_for(lambda: any(m.get("t") == "cur" for m in phone.messages))
        assert any(e == ("session", {"active": True, "device": "Test Phone"}) for e in events)

        # --- real mouse input: normalized coordinates -> actual cursor position ---
        mon = agent.source.current_monitor()
        for nx, ny in [(0.25, 0.25), (0.5, 0.5), (0.9, 0.8)]:
            phone.send({"t": "mm", "x": nx, "y": ny})
            ex, ey = mon["left"] + nx * (mon["width"] - 1), mon["top"] + ny * (mon["height"] - 1)
            assert await cursor_reaches(ex, ey), f"cursor {cursor()} != expected ({ex:.0f},{ey:.0f})"
        # relative move (from a known absolute position)
        phone.send({"t": "mm", "x": 0.5, "y": 0.5})
        bx, by = mon["left"] + round(0.5 * (mon["width"] - 1)), mon["top"] + round(0.5 * (mon["height"] - 1))
        assert await cursor_reaches(bx, by)
        phone.send({"t": "mr", "dx": 20, "dy": -10})
        assert await cursor_reaches(bx + 20, by - 10)

        # --- real keyboard: Shift held state ---
        phone.send({"t": "k", "c": "ShiftLeft", "d": True})
        assert await wait_for(lambda: user32.GetAsyncKeyState(0x10) & 0x8000, 5), "shift not pressed"
        phone.send({"t": "k", "c": "ShiftLeft", "d": False})
        assert await wait_for(lambda: not (user32.GetAsyncKeyState(0x10) & 0x8000), 5)

        # held key must be released when session drops
        phone.send({"t": "k", "c": "ShiftLeft", "d": True})
        assert await wait_for(lambda: user32.GetAsyncKeyState(0x10) & 0x8000, 5)
        # invalid input is rejected without crashing the session
        phone.send({"t": "mm", "x": "evil", "y": 0})
        phone.send({"t": "ping", "n": 7})
        assert await wait_for(lambda: {"t": "pong", "n": 7} in phone.messages, 5)

        # clipboard both ways (user's clipboard is saved/restored)
        from pocketdesk_agent.system import get_clipboard_text, set_clipboard_text
        try:
            orig_clip = get_clipboard_text()
        except Exception:
            orig_clip = ""
        phone.send({"t": "clip", "s": "héllo 😀 from phone"})
        assert await wait_for(lambda: get_clipboard_text() == "héllo 😀 from phone", 5)
        set_clipboard_text("pc side text")
        phone.send({"t": "clipget"})
        assert await wait_for(lambda: {"t": "clip", "s": "pc side text"} in phone.messages, 5)
        set_clipboard_text(orig_clip)

        # settings change at runtime
        phone.send({"t": "cfg", "maxw": 640, "fps": 10})
        assert await wait_for(lambda: agent.source.max_width == 640 and agent.source.fps == 10, 5)

        phone.send({"t": "bye"})
        assert await wait_for(lambda: agent.session is None, 10), "session did not end"
        assert await wait_for(lambda: not (user32.GetAsyncKeyState(0x10) & 0x8000), 5), "key stuck after disconnect"
        assert any(e[0] == "session" and e[1]["active"] is False for e in events)
    finally:
        user32.SetCursorPos(*saved_cursor)
        user32.keybd_event(0xA0, 0, 2, 0)
        await phone.close()
        await agent.stop()
        run.cancel()


@pytest.mark.asyncio
async def test_unauthorized_offers_are_rejected(server, tmp_path):
    cfg = Config(tmp_path / "agent.bin")
    cfg["server_url"] = server
    agent = Agent(cfg)
    run = asyncio.ensure_future(agent.run())
    phone = DevicePeer(server)
    try:
        assert await wait_for(lambda: agent.connected)
        await phone.pair(await agent.start_pairing())
        assert await wait_for(lambda: phone.device_id in cfg["devices"])
        await phone.connect_signaling()
        # 1) wrong MAC
        r = await phone.start_session(mac_override="00" * 32)
        assert r["type"] == "error" and agent.session is None
        await phone.pc.close()
        # 2) stale timestamp
        r = await phone.start_session(ts=int(time.time()) - 3600)
        assert r["type"] == "error" and agent.session is None
        await phone.pc.close()
        # 3) attacker who obtained a device token (but not the pair key) cannot control the PC
        phone.pair_key = b"\x01" * 32
        r = await phone.start_session()
        assert r["type"] == "error" and agent.session is None
        await phone.pc.close()
        # 4) after revocation nothing works
        phone.pair_key = None
        await agent.revoke_device(phone.device_id)
        assert phone.device_id not in cfg["devices"]
    finally:
        await phone.close()
        await agent.stop()
        run.cancel()
