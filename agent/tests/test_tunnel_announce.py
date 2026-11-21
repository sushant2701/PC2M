import json
import secrets
import time

import httpx
import pytest

from pocketdesk_agent import crypto
from pocketdesk_agent.config import Config
from pocketdesk_agent.tunnel import NTFY, build_announcement, publish


def test_announcement_signed_per_device(tmp_path):
    cfg = Config(tmp_path / "c.bin")
    k1, k2 = b"\x01" * 32, b"\x02" * 32
    cfg.add_device("d_1", "A", k1)
    cfg.add_device("d_2", "B", k2)
    a = build_announcement(cfg, "https://x.serveousercontent.com", ts=1000)
    assert crypto.verify(crypto.addr_mac(k1, a["u"], 1000), a["m"]["d_1"])
    assert crypto.verify(crypto.addr_mac(k2, a["u"], 1000), a["m"]["d_2"])
    assert a["m"]["d_1"] != a["m"]["d_2"]
    assert not crypto.verify(crypto.addr_mac(k1, "https://evil.example", 1000), a["m"]["d_1"])


@pytest.mark.asyncio
async def test_real_ntfy_roundtrip(tmp_path):
    """Uses the real public ntfy.sh service with a random throw-away topic (sends only a test URL)."""
    cfg = Config(tmp_path / "c.bin")
    key = secrets.token_bytes(32)
    cfg.add_device("d_t", "T", key)
    cfg["ntfy_topic"] = "pd-test-" + secrets.token_hex(12)
    try:
        await publish(cfg, "https://roundtrip.serveousercontent.com")
    except Exception as e:  # network unavailable
        pytest.skip(f"ntfy.sh unreachable: {e}")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{NTFY}/{cfg['ntfy_topic']}/json?poll=1&since=all")
    events = [json.loads(l) for l in r.text.strip().splitlines()]
    msg = json.loads([e for e in events if e["event"] == "message"][-1]["message"])
    assert msg["u"] == "https://roundtrip.serveousercontent.com"
    assert crypto.verify(crypto.addr_mac(key, msg["u"], msg["ts"]), msg["m"]["d_t"])
    assert abs(time.time() - msg["ts"]) < 60
