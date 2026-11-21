"""One remote-control WebRTC session: video track out, control data channel in/out."""
import asyncio
import json
import logging
import time

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.codecs import vpx

from .capture import DesktopTrack, ScreenSource
from .inputctl import InputController
from .system import get_clipboard_text, lock_workstation, set_clipboard_text

# Desktop text needs more bitrate than aiortc's webcam-oriented defaults. REMB still adapts downward.
vpx.DEFAULT_BITRATE = 1_500_000
vpx.MAX_BITRATE = 4_000_000

log = logging.getLogger("pocketdesk.session")
sec_log = logging.getLogger("pocketdesk.security")
MAX_CLIP = 50_000
IDLE_TIMEOUT = 30.0
QUALITY_PRESETS = {"low": (960, 12), "medium": (1280, 20), "high": (1920, 30)}


def make_rtc_config(ice_servers):
    servers = []
    for s in ice_servers or []:
        urls = s["urls"]
        servers.append(RTCIceServer(urls=urls, username=s.get("username"), credential=s.get("credential")))
    return RTCConfiguration(iceServers=servers)


class Session:
    def __init__(self, device_id, device_name, ice_servers, source: ScreenSource, on_end, max_seconds=12 * 3600):
        self.device_id, self.device_name = device_id, device_name
        self.src = source
        self.on_end = on_end
        self.pc = RTCPeerConnection(make_rtc_config(ice_servers))
        self.input = InputController(source.current_monitor, lambda: source.virtual)
        self.track = DesktopTrack(source)
        self.channel = None
        self.last_rx = time.monotonic()
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

    # ---- data channel ----
    def _send(self, obj):
        if self.channel and self.channel.readyState == "open":
            self.channel.send(json.dumps(obj, separators=(",", ":")))

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

    async def _housekeeping(self):
        n = 0
        while not self.closed:
            await asyncio.sleep(1 / 20)
            n += 1
            try:
                cx, cy = self.input.cursor_norm()
                self._send({"t": "cur", "x": round(cx, 4), "y": round(cy, 4)})
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
            if time.monotonic() - self.last_rx > IDLE_TIMEOUT and self.channel is not None:
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
