"""Performance measurement: agent runs as a separate process (real CLI); a real aiortc phone peer receives.
Reports received fps, bitrate, agent CPU%/RSS, RTT. Loopback network (not representative of WAN)."""
import asyncio
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "agent"), os.path.join(ROOT, "agent", "tests"), os.path.join(ROOT, "signaling")]
import psutil
import uvicorn
from device_peer import DevicePeer
from pocketdesk_signaling.app import create_app


async def measure(quality, seconds=10):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tmp = tempfile.mkdtemp()
    srv = uvicorn.Server(uvicorn.Config(create_app(os.path.join(tmp, "s.db"), stun_urls=[]), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        await asyncio.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    env = dict(os.environ, POCKETDESK_HOME=tmp, PYTHONPATH=os.path.join(ROOT, "agent"))
    subprocess.run([sys.executable, "-m", "pocketdesk_agent", "config", "--server", url], env=env, check=True, capture_output=True)
    p = subprocess.Popen([sys.executable, "-u", "-m", "pocketdesk_agent", "run", "--pair"], env=env, stdout=subprocess.PIPE, text=True)
    code = None
    for line in p.stdout:
        m = re.search(r"PAIRING CODE: (\S+)", line)
        if m:
            code = m.group(1)
            break
    threading.Thread(target=lambda: [None for _ in p.stdout], daemon=True).start()
    try:
        await _run(p, url, code, quality, seconds)
    finally:
        p.terminate()
        srv.should_exit = True


async def _run(p, url, code, quality, seconds):
    phone = DevicePeer(url)
    await phone.pair(code)
    await phone.connect_signaling()
    await phone.start_session()
    while phone.channel.readyState != "open":
        await asyncio.sleep(0.05)
    phone.send({"t": "cfg", "quality": quality})
    await asyncio.sleep(4)  # warm-up / bitrate ramp
    proc = psutil.Process(p.pid)
    proc.cpu_percent(None)
    n0, t0 = phone.video_frames.qsize(), time.time()
    while not phone.video_frames.empty():
        phone.video_frames.get_nowait()
    count, last = 0, None
    t0 = time.time()
    phone.messages.clear()
    while time.time() - t0 < seconds:
        try:
            last = await asyncio.wait_for(phone.video_frames.get(), 2)
            count += 1
        except asyncio.TimeoutError:
            break
    dt = time.time() - t0
    kb = [m["kbps"] for m in phone.messages if m.get("t") == "stats" and "kbps" in m]
    mbit = (sum(kb) / len(kb) / 1000) if kb else float("nan")
    cpu = proc.cpu_percent(None) / psutil.cpu_count()
    rss = proc.memory_info().rss / 1e6
    print(f"quality={quality:6s} fps={count/dt:5.1f} size={last.width}x{last.height} bitrate={mbit:5.2f} Mbit/s (agent-reported, static desktop) "
          f"agent_cpu={cpu:5.1f}% (of all {psutil.cpu_count()} cores) agent_rss={rss:5.0f} MB")
    try:
        await phone.close()
    except Exception:
        pass


async def main():
    for q in ("low", "medium", "high"):
        await measure(q)


asyncio.run(main())
