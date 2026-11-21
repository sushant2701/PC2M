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
