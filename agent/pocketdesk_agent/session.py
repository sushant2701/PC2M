"""Remote-control sessions: WebRTC (direct/TURN) and an encrypted WebSocket relay fallback."""
import asyncio
import io
import json
import logging
import time

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.codecs import vpx

from .capture import DesktopTrack, ScreenSource
from .inputctl import InputController
from .system import get_clipboard_text, is_locked, lock_workstation, set_clipboard_text

# Desktop text needs more bitrate than aiortc's webcam-oriented defaults. REMB still adapts downward.
vpx.DEFAULT_BITRATE = 1_500_000
vpx.MAX_BITRATE = 4_000_000

log = logging.getLogger("pocketdesk.session")
sec_log = logging.getLogger("pocketdesk.security")
MAX_CLIP = 50_000
IDLE_TIMEOUT = 30.0
QUALITY_PRESETS = {"low": (960, 12), "medium": (1280, 20), "high": (1920, 30)}
RELAY_PRESETS = {"low": (960, 6, 45), "medium": (1280, 10, 55), "high": (1600, 15, 65)}  # width, fps, jpeg quality


def make_rtc_config(ice_servers):
    servers = []
    for s in ice_servers or []:
        servers.append(RTCIceServer(urls=s["urls"], username=s.get("username"), credential=s.get("credential")))
    return RTCConfiguration(iceServers=servers)


class ControlHandler:
    """Shared handling of authenticated control messages (input, settings, clipboard, lock)."""
    device_name: str

    def _init_control(self, source: ScreenSource):
        self.src = source
        self.input = InputController(source.current_monitor, lambda: source.virtual)
        self.last_rx = time.monotonic()
        self._locked = None

    def _send(self, obj):  # implemented by subclasses
        raise NotImplementedError

    def _check_lock(self, force=False):
        """Tell the phone when Windows shows the lock screen (cannot be captured/controlled by a normal app)."""
        lk = is_locked()
        if lk != self._locked or force:
            self._locked = lk
            self._send({"t": "state", "locked": lk})

    def _send_info(self):
        m = self.src.current_monitor()
        self._send({"t": "info", "monitors": [{"i": i, "w": x["width"], "h": x["height"]} for i, x in enumerate(self.src.monitors)],
                    "monitor": self.src.monitor, "w": m["width"], "h": m["height"], "backend": self.src.backend})

    def _on_message(self, raw):
        self.last_rx = time.monotonic()
        try:
            m = json.loads(raw)
            if not isinstance(m, dict):
                return
            t = m.get("t")
            if t == "ping":
                self._send({"t": "pong", "n": m.get("n")})
            elif t == "cfg":
                self._apply_cfg(m)
            elif t == "bye":
                asyncio.ensure_future(self.close("remote hangup"))
            elif t == "clip":  # phone -> PC clipboard (text only, user-triggered in the app)
                s = m.get("s")
                if not isinstance(s, str) or len(s) > MAX_CLIP:
                    raise ValueError("bad clipboard")
                set_clipboard_text(s)
            elif t == "clipget":  # PC -> phone clipboard (text only, user-triggered in the app)
                self._send({"t": "clip", "s": (get_clipboard_text() or "")[:MAX_CLIP]})
            elif t == "lock":  # lock workstation (non-destructive); phone UI asks for confirmation first
                sec_log.info("remote lock requested by %s", self.device_name)
                lock_workstation()
            else:
                self.input.handle(m)
        except (ValueError, KeyError, TypeError) as e:
            log.warning("rejected control message: %s", e)

    def _apply_cfg(self, m):
        mw, fps = m.get("maxw"), m.get("fps")
        q = m.get("quality")
        if q in QUALITY_PRESETS:
            mw, fps = QUALITY_PRESETS[q]
        mon = m.get("monitor")
        kw = {}
        if isinstance(mw, int) and 320 <= mw <= 3840:
            kw["max_width"] = mw
        if isinstance(fps, int) and 1 <= fps <= 60:
            kw["fps"] = fps
        if isinstance(mon, int) and 0 <= mon < len(self.src.monitors):
            kw["monitor"] = mon
        self.src.configure(**kw)
        self._send_info()


class Session(ControlHandler):
    kind = "webrtc"

    def __init__(self, device_id, device_name, ice_servers, source: ScreenSource, on_end, max_seconds=30 * 24 * 3600):
        self.device_id, self.device_name = device_id, device_name
        self._init_control(source)
        self.on_end = on_end
        self.pc = RTCPeerConnection(make_rtc_config(ice_servers))
        self.track = DesktopTrack(source)
        self.channel = None
        self.started = time.monotonic()
        self.max_seconds = max_seconds
        self.closed = False
        self._tasks = []
        self._last_sent = 0
        self._last_t = time.monotonic()
        self._last_bytes, self._last_bt = 0, time.monotonic()

        @self.pc.on("connectionstatechange")
        async def _state():
            log.info("session %s state=%s", device_name, self.pc.connectionState)
            if self.pc.connectionState in ("failed", "closed", "disconnected"):
                if self.pc.connectionState == "disconnected":
                    await asyncio.sleep(8)
                    if self.pc.connectionState != "disconnected":
                        return
                await self.close("connection " + self.pc.connectionState)

        @self.pc.on("datachannel")
        def _dc(ch):
            if ch.label != "control":
                return
            self.channel = ch
            ch.on("message", self._on_message)
            self._send_info()

    async def accept(self, offer_sdp: str) -> str:
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
        self.pc.addTrack(self.track)
        for t in self.pc.getTransceivers():  # prefer VP8 (software-friendly, universal)
            if t.kind == "video":
                caps = [c for c in t.sender.getCapabilities("video").codecs if c.mimeType == "video/VP8"]
                if caps:
                    t.setCodecPreferences(caps)
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        self._tasks.append(asyncio.ensure_future(self._housekeeping()))
        return self.pc.localDescription.sdp

    def _send(self, obj):
        if self.channel and self.channel.readyState == "open":
            self.channel.send(json.dumps(obj, separators=(",", ":")))

    async def _housekeeping(self):
        n = 0
        connect_deadline = time.monotonic() + 60
        while not self.closed:
            await asyncio.sleep(1 / 20)
            n += 1
            try:
                cx, cy = self.input.cursor_norm()
                self._send({"t": "cur", "x": round(cx, 4), "y": round(cy, 4)})
                if n % 10 == 0:
                    self._check_lock(force=(n % 100 == 0))
                if n % 20 == 0:
                    now = time.monotonic()
                    fps = (self.track.sent - self._last_sent) / max(0.001, now - self._last_t)
                    self._last_sent, self._last_t = self.track.sent, now
                    f = self.src.latest()
                    sent = sum(getattr(v, "bytesSent", 0) for v in (await self.pc.getStats()).values()
                               if v.type == "outbound-rtp" and v.kind == "video")
                    kbps = (sent - self._last_bytes) * 8 / 1000 / max(0.001, now - self._last_bt)
                    self._last_bytes, self._last_bt = sent, now
                    self._send({"t": "stats", "fps": round(fps, 1), "kbps": round(kbps), "w": f.width if f else 0,
                                "h": f.height if f else 0, "backend": self.src.backend})
            except Exception as e:  # noqa
                log.debug("housekeeping: %s", e)
            if self.channel is None and time.monotonic() > connect_deadline:
                await self.close("never connected")
            elif self.channel is not None and time.monotonic() - self.last_rx > IDLE_TIMEOUT:
                await self.close("idle timeout")
            elif time.monotonic() - self.started > self.max_seconds:
                await self.close("session expired")

    async def close(self, reason="closed"):
        if self.closed:
            return
        self.closed = True
        log.info("session with %s ended: %s", self.device_name, reason)
        try:
            self.input.release_all()
        except Exception:
            pass
        for t in self._tasks:
            if t is not asyncio.current_task():
                t.cancel()
        try:
            await self.pc.close()
        except Exception:
            pass
        self.track.stop()
        self.on_end(self, reason)


class RelaySession(ControlHandler):
    """Fallback when no direct/TURN path exists: JPEG frames + control, AES-GCM encrypted end-to-end with keys
    derived from the pair key, carried over the signaling WebSocket (the server only sees ciphertext)."""
    kind = "relay"
    A2D, D2A = b"relay-a2d", b"relay-d2a"

    def __init__(self, device_id, device_name, source: ScreenSource, pair_key: bytes, session_id: str, send_bytes, on_end,
                 max_seconds=30 * 24 * 3600):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from .crypto import hkdf_sha256
        self.device_id, self.device_name = device_id, device_name
        self._init_control(source)
        sid = bytes.fromhex(session_id)
        self._tx = AESGCM(hkdf_sha256(pair_key, sid, self.A2D, 32))
        self._rx = AESGCM(hkdf_sha256(pair_key, sid, self.D2A, 32))
        self._tx_n, self._rx_n = 0, -1
        self._send_bytes = send_bytes  # async callable(bytes)
        self.on_end = on_end
        self.closed = False
        self.started = time.monotonic()
        self.max_seconds = max_seconds
        self.jpeg_q = 55
        self._tasks = []
        self._sent_bytes = 0
        self._sent_frames = 0
        self._queue = asyncio.Queue(maxsize=8)
        sec_log.info("relay session prepared for %s", device_name)

    # ---- crypto framing: counter(8) || AESGCM(type(1)||payload) ----
    def _seal(self, typ: int, payload: bytes) -> bytes:
        n = self._tx_n
        self._tx_n += 1
        ctr = n.to_bytes(8, "big")
        return ctr + self._tx.encrypt(b"\0\0\0\0" + ctr, bytes([typ]) + payload, self.A2D)

    def _open(self, data: bytes):
        ctr = data[:8]
        n = int.from_bytes(ctr, "big")
        if n <= self._rx_n:
            raise ValueError("replayed relay frame")
        pt = self._rx.decrypt(b"\0\0\0\0" + ctr, data[8:], self.D2A)
        self._rx_n = n
        return pt[0], pt[1:]

    def on_data(self, data: bytes):
        try:
            typ, payload = self._open(data)
        except Exception as e:  # bad tag / replay: drop silently, log
            log.warning("relay frame rejected: %s", e)
            return
        if typ == 2:
            self._on_message(payload.decode("utf-8", "replace"))

    def _send(self, obj):
        self._enqueue(self._seal(2, json.dumps(obj, separators=(",", ":")).encode()), droppable=True)

    def _enqueue(self, blob, droppable=False):
        try:
            self._queue.put_nowait(blob)
        except asyncio.QueueFull:
            if not droppable:
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self._queue.put_nowait(blob)

    def _apply_cfg(self, m):
        q = m.get("quality")
        if q in RELAY_PRESETS:
            mw, fps, jq = RELAY_PRESETS[q]
            self.jpeg_q = jq
            self.src.configure(max_width=mw, fps=fps)
        mon = m.get("monitor")
        if isinstance(mon, int) and 0 <= mon < len(self.src.monitors):
            self.src.configure(monitor=mon)
        self._send_info()

    def start(self):
        self._tasks = [asyncio.ensure_future(self._writer()), asyncio.ensure_future(self._video()),
                       asyncio.ensure_future(self._housekeeping())]
        self._send_info()

    async def _writer(self):
        try:
            while not self.closed:
                blob = await self._queue.get()
                await self._send_bytes(blob)
                self._sent_bytes += len(blob)
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa
            log.warning("relay writer stopped: %s", e)
            await self.close("relay connection lost")

    def _encode(self, frame):
        buf = io.BytesIO()
        frame.to_image().save(buf, "JPEG", quality=self.jpeg_q, optimize=False)
        return buf.getvalue()

    async def _video(self):
        loop = asyncio.get_running_loop()
        last_count, last_send = -1, 0.0
        try:
            while not self.closed:
                await asyncio.sleep(1.0 / max(1, self.src.fps))
                f = self.src.latest()
                if f is None:
                    continue
                now = time.monotonic()
                if self.src.captured == last_count and now - last_send < 3:
                    continue  # screen unchanged
                if self._queue.qsize() > 2:
                    continue  # link is slower than capture: skip frames instead of lagging
                last_count, last_send = self.src.captured, now
                jpg = await loop.run_in_executor(None, self._encode, f)
                self._enqueue(self._seal(1, jpg), droppable=True)
                self._sent_frames += 1
        except asyncio.CancelledError:
            pass

    async def _housekeeping(self):
        n, last_b, last_f, last_t = 0, 0, 0, time.monotonic()
        try:
            while not self.closed:
                await asyncio.sleep(1 / 12)
                n += 1
                cx, cy = self.input.cursor_norm()
                self._send({"t": "cur", "x": round(cx, 4), "y": round(cy, 4)})
                if n % 6 == 0:
                    self._check_lock(force=(n % 72 == 0))
                if n % 12 == 0:
                    now = time.monotonic()
                    dt = max(0.001, now - last_t)
                    self._send({"t": "stats", "fps": round((self._sent_frames - last_f) / dt, 1),
                                "kbps": round((self._sent_bytes - last_b) * 8 / 1000 / dt), "mode": "relay"})
                    last_b, last_f, last_t = self._sent_bytes, self._sent_frames, now
                if time.monotonic() - self.last_rx > IDLE_TIMEOUT:
                    await self.close("idle timeout")
                elif time.monotonic() - self.started > self.max_seconds:
                    await self.close("session expired")
        except asyncio.CancelledError:
            pass

    async def close(self, reason="closed"):
        if self.closed:
            return
        self.closed = True
        log.info("relay session with %s ended: %s", self.device_name, reason)
        try:
            self.input.release_all()
        except Exception:
            pass
        for t in self._tasks:
            if t is not asyncio.current_task():
                t.cancel()
        self.on_end(self, reason)
