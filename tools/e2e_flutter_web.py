"""Drives the Flutter client's real Dart protocol code (running in Chrome) against a real agent + signaling server.
Run: python tools/e2e_flutter_web.py   (needs Chrome + flutter; moves the real mouse cursor briefly)."""
import asyncio
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "agent"), os.path.join(ROOT, "signaling")]
import tempfile
import uvicorn
from pocketdesk_agent.agent import Agent
from pocketdesk_agent.config import Config
from pocketdesk_signaling.app import create_app


def cursor():
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


async def main():
    s = socket.socket(); s.bind(("0.0.0.0", 0)); port = s.getsockname()[1]; s.close()
    tmp = tempfile.mkdtemp()
    app = create_app(os.path.join(tmp, "s.db"), stun_urls=[], cors_origins=["*"])
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        await asyncio.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    cfg = Config(os.path.join(tmp, "agent.bin") and __import__("pathlib").Path(tmp) / "agent.bin")
    cfg["server_url"] = url
    events = []
    agent = Agent(cfg, lambda k, d=None: events.append((k, d)))
    run = asyncio.ensure_future(agent.run())
    while not agent.connected:
        await asyncio.sleep(0.1)
    code = await agent.start_pairing()
    saved = cursor()
    proc = subprocess.Popen(
        ["flutter", "test", "--platform", "chrome", "test/e2e_web_test.dart", f"--dart-define=PD_SERVER={url}",
         f"--dart-define=PD_CODE={code}"], cwd=os.path.join(ROOT, "mobile"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True)
    out = []
    threading.Thread(target=lambda: [out.append(l) for l in proc.stdout], daemon=True).start()
    target = (round(0.3 * 1919), round(0.6 * 1079))
    cursor_hit = shift_seen = False
    while proc.poll() is None:
        x, y = cursor()
        cursor_hit |= abs(x - target[0]) <= 2 and abs(y - target[1]) <= 2
        shift_seen |= bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
        await asyncio.sleep(0.005)
    ctypes.windll.user32.SetCursorPos(*saved)
    text = "".join(out)
    session_started = any(e[0] == "session" and e[1]["active"] for e in events)
    print(text[-1500:])
    print(f"RESULT flutter_exit={proc.returncode} session_started={session_started} cursor_hit={cursor_hit} shift_seen={shift_seen}")
    await agent.stop(); run.cancel(); srv.should_exit = True
    return 0 if proc.returncode == 0 and session_started and cursor_hit else 1


sys.exit(asyncio.run(main()))

