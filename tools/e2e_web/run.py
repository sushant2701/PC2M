"""REAL end-to-end test of the web client: headless Chrome -> real server -> real agent -> real PC cursor.
Usage: python tools/e2e_web/run.py   (needs Chrome + `npm install` in this folder; moves the real mouse briefly)."""
import asyncio, ctypes, os, socket, subprocess, sys, tempfile, threading
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "signaling")]
import uvicorn
from pocketdesk_agent.agent import Agent
from pocketdesk_agent.config import Config
from pocketdesk_signaling.app import create_app

W, H = 1920, 1080


def cursor():
    pt = wintypes.POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)); return pt.x, pt.y


async def scenario(mode):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tmp = Path(tempfile.mkdtemp())
    srv = uvicorn.Server(uvicorn.Config(create_app(str(tmp / "s.db"), stun_urls=[]), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        await asyncio.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    cfg = Config(tmp / "agent.bin"); cfg["server_url"] = url
    agent = Agent(cfg); run = asyncio.ensure_future(agent.run())
    while not agent.connected:
        await asyncio.sleep(0.1)
    code = await agent.start_pairing()
    saved = cursor()
    proc = await asyncio.create_subprocess_exec("node", "e2e_web.js", url, code, mode, cwd=str(HERE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    seen_center = seen_rot = False
    out = []
    async def reader():
        async for line in proc.stdout:
            out.append(line.decode(errors="replace").rstrip())
    rt = asyncio.ensure_future(reader())
    while proc.returncode is None:
        x, y = cursor()
        seen_center |= abs(x - 0.5 * (W - 1)) <= 25 and abs(y - 0.5 * (H - 1)) <= 25
        seen_rot |= abs(x - 0.5 * (W - 1)) <= 25 and abs(y - 0.146 * (H - 1)) <= 25
        try:
            await asyncio.wait_for(proc.wait(), 0.005)
        except asyncio.TimeoutError:
            pass
    await rt
    ctypes.windll.user32.SetCursorPos(*saved)
    sess = agent.session
    await agent.stop(); run.cancel(); srv.should_exit = True
    ok = proc.returncode == 0 and "STAGE_CONNECTED" in "\n".join(out) and seen_center and seen_rot and "SIGNED_OUT none" not in "\n".join(out)
    print(f"--- {mode}: exit={proc.returncode} center_hit={seen_center} rotated_hit={seen_rot}")
    print("\n".join(out[-12:]))
    return ok


async def main():
    res = [await scenario("direct"), await scenario("relay")]
    print("RESULT", res)
    return 0 if all(res) else 1

sys.exit(asyncio.run(main()))
