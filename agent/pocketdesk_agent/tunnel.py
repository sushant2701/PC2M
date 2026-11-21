"""Self-restarting public tunnel (Windows built-in ssh -> serveo.net, no admin) + signed address announcements.

The free tunnel address changes whenever the tunnel restarts. After every change (and every 20 min as a heartbeat) the agent
announces the current address on a private ntfy.sh topic (random 128-bit name, known only to this PC and its paired phones).
Each message is HMAC-signed per paired phone with that phone's pair key, so nobody (including ntfy.sh) can redirect a phone to
a fake address. The announcement contains only the public URL — never credentials."""
import asyncio
import json
import logging
import re
import secrets
import shutil
import subprocess
import time

import httpx

from . import crypto
from .config import data_dir

log = logging.getLogger("pocketdesk.tunnel")
URL_RE = re.compile(r"https://\S+serveousercontent\.com")
NTFY = "https://ntfy.sh"


def ensure_topic(cfg) -> str:
    if not cfg["ntfy_topic"]:
        cfg["ntfy_topic"] = "pd-" + secrets.token_hex(16)
        cfg.save()
    return cfg["ntfy_topic"]


def build_announcement(cfg, url: str, ts: int = None) -> dict:
    ts = int(time.time()) if ts is None else ts
    macs = {did: crypto.addr_mac(bytes.fromhex(d["key"]), url, ts) for did, d in cfg["devices"].items()}
    return {"u": url, "ts": ts, "m": macs}


async def publish(cfg, url: str):
    topic = ensure_topic(cfg)
    body = json.dumps(build_announcement(cfg, url), separators=(",", ":"))
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{NTFY}/{topic}", content=body.encode(), headers={"Cache": "yes"})
        r.raise_for_status()
    log.info("announced tunnel address")


class Tunnel:
    def __init__(self, cfg, local_port=8080):
        self.cfg, self.port = cfg, local_port
        self.url = None
        self._stop = False
        self._proc = None
        self.url_file = data_dir() / "public_url.txt"

    def _key(self):
        key = data_dir() / "tunnel_key"
        if not key.exists():
            subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key), "-q"], check=True,
                           creationflags=0x08000000)
        return key

    def _name(self):
        f = data_dir() / "tunnel_name.txt"
        if not f.exists():
            f.write_text("pd-" + secrets.token_hex(4))
        return f.read_text().strip()

    async def run(self):
        ssh = shutil.which("ssh")
        if not ssh:
            log.error("ssh not found; tunnel disabled")
            return
        asyncio.ensure_future(self._heartbeat())
        while not self._stop:
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    ssh, "-i", str(self._key()), "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-o", "ExitOnForwardFailure=yes",
                    "-R", f"{self._name()}:80:127.0.0.1:{self.port}", "serveo.net",
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    creationflags=0x08000000)
                async for line in self._proc.stdout:
                    m = URL_RE.search(line.decode(errors="replace"))
                    if m and m.group(0) != self.url:
                        self.url = m.group(0)
                        self.url_file.write_text(self.url)
                        log.info("tunnel up: %s", self.url)
                        asyncio.ensure_future(self._announce())
                await self._proc.wait()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa
                log.warning("tunnel error: %s", e)
            self.url = None
            try:
                self.url_file.unlink()
            except OSError:
                pass
            log.warning("tunnel dropped; restarting")
            await asyncio.sleep(3)

    async def _announce(self):
        for delay in (0, 5, 15, 60):
            await asyncio.sleep(delay)
            if not self.url:
                return
            try:
                await publish(self.cfg, self.url)
                return
            except Exception as e:  # noqa
                log.warning("announce failed: %s", e)

    async def _heartbeat(self):
        while not self._stop:
            await asyncio.sleep(20 * 60)
            if self.url:
                await self._announce()

    async def stop(self):
        self._stop = True
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
