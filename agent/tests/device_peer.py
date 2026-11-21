"""A real (non-mocked) PocketDesk *phone-side* peer implemented with aiortc.
Follows the same protocol as the Flutter app; used by integration tests and for CLI diagnostics."""
import asyncio
import json
import secrets
import time

import httpx
import websockets
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

from pocketdesk_agent import crypto


class DevicePeer:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.pair_key = None
        self.device_id = self.token = self.agent_id = None
        self.pc = None
        self.channel = None
        self.messages = []
        self.video_frames = asyncio.Queue()
        self.ws = None

    async def pair(self, code_display, name="Test Phone"):
        lookup, secret = crypto.parse_pairing_code(code_display)
        self.pair_key = crypto.derive_pair_key(secret)
        proof = crypto.claim_proof(self.pair_key, lookup, name)
        async with httpx.AsyncClient() as c:
            r = await c.post(self.base + "/api/pair/claim", json={"code": lookup, "device_name": name, "proof": proof})
        r.raise_for_status()
        j = r.json()
        self.device_id, self.token, self.agent_id = j["device_id"], j["device_token"], j["agent_id"]
        return j

    async def connect_signaling(self):
        url = self.base.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
        self.ws = await websockets.connect(url)
        await self.ws.send(json.dumps({"type": "auth", "role": "device", "id": self.device_id, "secret": self.token}))
        ready = json.loads(await self.ws.recv())
        assert ready["type"] == "ready", ready
        self.ice = ready["ice_servers"]

    async def _recv_type(self, *types, timeout=20):
        end = time.time() + timeout
        while True:
            m = json.loads(await asyncio.wait_for(self.ws.recv(), max(0.1, end - time.time())))
            if m["type"] in types:
                return m

    async def start_session(self, mac_override=None, session_id=None, ts=None):
        servers = [RTCIceServer(urls=s["urls"], username=s.get("username"), credential=s.get("credential")) for s in self.ice]
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        self.channel = self.pc.createDataChannel("control", ordered=True)
        self.channel.on("message", lambda m: self.messages.append(json.loads(m)))
        self.pc.addTransceiver("video", direction="recvonly")

        @self.pc.on("track")
        def _track(t):
            async def pump():
                while True:
                    try:
                        await self.video_frames.put(await t.recv())
                    except Exception:
                        return
            asyncio.ensure_future(pump())

        await self.pc.setLocalDescription(await self.pc.createOffer())
        sdp = self.pc.localDescription.sdp
        sid = session_id or secrets.token_hex(16)
        ts = int(time.time()) if ts is None else ts
        mac = mac_override or crypto.offer_mac(self.pair_key, sid, self.device_id, ts, sdp)
        await self.ws.send(json.dumps({"type": "offer", "agent_id": self.agent_id, "session_id": sid, "ts": ts, "sdp": sdp, "mac": mac}))
        m = await self._recv_type("answer", "error", "agent_offline")
        if m["type"] != "answer":
            return m
        expect = crypto.answer_mac(self.pair_key, sid, self.device_id, int(m["ts"]), m["sdp"])
        if not crypto.verify(expect, m["mac"]):
            raise RuntimeError("answer MAC invalid (possible MITM)")
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=m["sdp"], type="answer"))
        return m

    def send(self, obj):
        if getattr(self, "relay", False):
            self._relay_send(2, json.dumps(obj).encode())
        else:
            self.channel.send(json.dumps(obj))

    # ---- encrypted WebSocket relay mode (same wire format as the browser client) ----
    async def start_relay(self, mac_override=None, ts=None):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        sid = secrets.token_hex(16)
        ts = int(time.time()) if ts is None else ts
        mac = mac_override or crypto.relay_mac(self.pair_key, sid, self.device_id, ts)
        await self.ws.send(json.dumps({"type": "relay_start", "session_id": sid, "ts": ts, "mac": mac}))
        m = await self._recv_type("relay_ok", "error", "agent_offline")
        if m["type"] != "relay_ok":
            return m
        assert crypto.verify(crypto.relay_ok_mac(self.pair_key, sid, self.device_id, int(m["ts"])), m["mac"]), "relay_ok MAC invalid"
        sidb = bytes.fromhex(sid)
        self._rtx = AESGCM(crypto.hkdf_sha256(self.pair_key, sidb, b"relay-d2a", 32))
        self._rrx = AESGCM(crypto.hkdf_sha256(self.pair_key, sidb, b"relay-a2d", 32))
        self._tx_n = 0
        self.relay = True
        self.relay_frames = []
        self.relay_task = asyncio.ensure_future(self._relay_pump())
        return m

    def _relay_send(self, typ, payload):
        ctr = self._tx_n.to_bytes(8, "big")
        self._tx_n += 1
        blob = ctr + self._rtx.encrypt(b"\0\0\0\0" + ctr, bytes([typ]) + payload, b"relay-d2a")
        asyncio.ensure_future(self.ws.send(blob))

    async def _relay_pump(self):
        last = -1
        async for raw in self.ws:
            if isinstance(raw, str):
                continue
            n = int.from_bytes(raw[:8], "big")
            assert n > last, "replayed frame"
            last = n
            pt = self._rrx.decrypt(b"\0\0\0\0" + raw[:8], raw[8:], b"relay-a2d")
            if pt[0] == 1:
                self.relay_frames.append(pt[1:])
            elif pt[0] == 2:
                self.messages.append(json.loads(pt[1:]))

    async def close(self):
        if self.pc:
            await self.pc.close()
        if self.ws:
            await self.ws.close()
