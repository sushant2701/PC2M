"""Agent core: registration, signaling connection, pairing, authenticated session lifecycle."""
import asyncio
import json
import logging
import time
from collections import deque

import httpx
import websockets

from . import crypto
from .capture import ScreenSource, set_dpi_aware
from .config import Config
from .session import Session

log = logging.getLogger("pocketdesk.agent")
sec_log = logging.getLogger("pocketdesk.security")
TS_WINDOW = 120


def is_local_host(url: str) -> bool:
    from urllib.parse import urlparse
    h = urlparse(url).hostname or ""
    return h in ("localhost", "127.0.0.1", "::1") or h.startswith(("192.168.", "10.", "172.16.", "172.17.", "172.18."))


def check_server_url(url: str):
    if url.startswith("https://") or (url.startswith("http://") and is_local_host(url)):
        return
    raise ValueError("Server URL must be https:// (plain http only allowed for localhost/LAN testing)")


class Agent:
    def __init__(self, cfg: Config, on_event=lambda kind, data=None: None):
        self.cfg = cfg
        self.emit = on_event
        self.session: Session | None = None
        self.source: ScreenSource | None = None
        self.ice_servers = []
        self.ws = None
        self.connected = False
        self._pending = None  # {lookup, key, expires, display}
        self._seen = deque(maxlen=2000)
        self._stop = asyncio.Event()

    # ---------- registration / pairing ----------
    @property
    def base(self):
        return self.cfg["server_url"].rstrip("/")

    def _auth_header(self):
        return {"Authorization": f"Bearer {self.cfg['agent_id']}:{self.cfg['agent_secret']}"}

    async def ensure_registered(self):
        check_server_url(self.base)
        if self.cfg["agent_id"]:
            return
        hdr = {"X-Register-Key": self.cfg["register_key"]} if self.cfg["register_key"] else {}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(self.base + "/api/agents/register", json={"name": self.cfg["name"] or "My PC"}, headers=hdr)
            r.raise_for_status()
        self.cfg["agent_id"], self.cfg["agent_secret"] = r.json()["agent_id"], r.json()["agent_secret"]
        self.cfg.save()
        sec_log.info("registered agent %s", self.cfg["agent_id"])

    async def start_pairing(self) -> str:
        """Create a one-time pairing code (valid 5 min). Returns display string."""
        await self.ensure_registered()
        for _ in range(5):
            lookup, secret, disp = crypto.new_pairing_code()
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(self.base + "/api/agents/pair-code", json={"lookup": lookup}, headers=self._auth_header())
            if r.status_code == 409:
                continue
            r.raise_for_status()
            self._pending = {"lookup": lookup, "key": crypto.derive_pair_key(secret), "expires": time.time() + r.json()["expires_in"],
                             "display": disp}
            sec_log.info("pairing code issued")
            self.emit("pairing_code", disp)
            return disp
        raise RuntimeError("could not allocate pairing code")

    # ---------- main loop ----------
    async def run(self):
        set_dpi_aware()
        backoff = 1
        while not self._stop.is_set():
            try:
                await self.ensure_registered()
                url = self.base.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
                async with websockets.connect(url, max_size=2 ** 17, ping_interval=20, ping_timeout=20) as ws:
                    self.ws = ws
                    await ws.send(json.dumps({"type": "auth", "role": "agent", "id": self.cfg["agent_id"], "secret": self.cfg["agent_secret"]}))
                    self.connected = True
                    backoff = 1
                    self.emit("status", "online")
                    async for raw in ws:
                        await self._on_signal(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("signaling connection lost: %s", e)
            self.connected = False
            self.ws = None
            self.emit("status", "offline")
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(60, backoff * 2)
        await self.end_session("agent stopping")

    async def stop(self):
        self._stop.set()
        await self.end_session("agent stopping")
        if self.ws:
            await self.ws.close()

    async def _send(self, obj):
        if self.ws:
            await self.ws.send(json.dumps(obj))

    async def _on_signal(self, m: dict):
        t = m.get("type")
        if t == "ready":
            self.ice_servers = m.get("ice_servers", [])
        elif t == "paired":
            await self._on_paired(m)
        elif t == "offer":
            await self._on_offer(m)
        elif t == "bye":
            if self.session and self.session.device_id == m.get("device_id"):
                await self.end_session("remote hangup")
        elif t == "device_revoked":
            did = m.get("device_id")
            self.cfg.remove_device(did)
            sec_log.info("device %s revoked", did)
            if self.session and self.session.device_id == did:
                await self.end_session("device revoked")
            self.emit("devices", self.cfg["devices"])

    async def _on_paired(self, m):
        p = self._pending
        did = str(m.get("device_id"))
        name = str(m.get("device_name", ""))[:64]
        if p and p["expires"] > time.time() and p["lookup"] == m.get("lookup") and \
                crypto.verify(crypto.claim_proof(p["key"], p["lookup"], name), str(m.get("proof"))):
            self.cfg.add_device(did, name, p["key"])
            self._pending = None
            sec_log.info("paired device %s (%s)", did, name)
            self.emit("paired", {"id": did, "name": name})
            self.emit("devices", self.cfg["devices"])
        else:
            sec_log.warning("pairing proof rejected for device %s; revoking", did)
            await self._send({"type": "revoke", "device_id": did})

    async def _on_offer(self, m):
        did, sid = str(m.get("device_id")), str(m.get("session_id"))
        key = self.cfg.device_key(did)
        try:
            ts = int(m["ts"])
            sdp = m["sdp"]
            if key is None:
                raise ValueError("unknown device")
            if abs(time.time() - ts) > TS_WINDOW:
                raise ValueError("stale timestamp")
            if (did, sid) in self._seen:
                raise ValueError("replayed session id")
            if not crypto.verify(crypto.offer_mac(key, sid, did, ts, sdp), str(m.get("mac"))):
                raise ValueError("bad MAC")
        except (ValueError, KeyError, TypeError) as e:
            sec_log.warning("offer rejected from %s: %s", did, e)
            await self._send({"type": "error", "device_id": did, "session_id": sid, "error": "rejected"})
            return
        self._seen.append((did, sid))
        await self.end_session("replaced by new connection")
        name = self.cfg["devices"][did]["name"]
        if self.source is None:
            self.source = ScreenSource(max_width=self.cfg["max_width"], fps=self.cfg["fps"])
        self.source.start()
        sess = Session(did, name, self.ice_servers, self.source, self._session_ended)
        self.session = sess
        try:
            answer = await sess.accept(sdp)
        except Exception as e:
            log.exception("session setup failed")
            await sess.close("setup failed")
            await self._send({"type": "error", "device_id": did, "session_id": sid, "error": "setup failed"})
            return
        sec_log.info("session started with %s (%s)", name, did)
        self.emit("session", {"active": True, "device": name})
        await self._send({"type": "answer", "device_id": did, "session_id": sid, "ts": ts, "sdp": answer,
                          "mac": crypto.answer_mac(key, sid, did, ts, answer)})

    def _session_ended(self, sess, reason):
        if self.session is sess:
            self.session = None
            if self.source:
                self.source.stop()
                self.source = None
            self.emit("session", {"active": False, "device": sess.device_name, "reason": reason})
            sec_log.info("session ended: %s", reason)

    async def end_session(self, reason="ended"):
        s = self.session
        if s:
            await s.close(reason)

    async def revoke_device(self, did):
        self.cfg.remove_device(did)
        async with httpx.AsyncClient(timeout=15) as c:
            await c.delete(self.base + f"/api/devices/{did}", headers=self._auth_header())
        if self.session and self.session.device_id == did:
            await self.end_session("device revoked")
        self.emit("devices", self.cfg["devices"])
