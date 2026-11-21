"""Desktop capture: DXGI Desktop Duplication (dxcam) with GDI (mss) fallback, plus an aiortc video track."""
import asyncio
import ctypes
import fractions
import logging
import sys
import threading
import time

import av
import numpy as np
from aiortc import MediaStreamTrack

log = logging.getLogger("pocketdesk.capture")
VIDEO_CLOCK = 90000


def set_dpi_aware():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def list_monitors():
    """Physical monitors as dicts (left, top, width, height) in virtual-desktop pixels, plus virtual rect."""
    import mss
    with mss.MSS() as s:
        mons = [{"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]} for m in s.monitors[1:]]
        virt = dict(s.monitors[0])
    return mons, {"left": virt["left"], "top": virt["top"], "width": virt["width"], "height": virt["height"]}


class ScreenSource:
    """Background thread grabbing the selected monitor, scaling to max_width, producing yuv420p av frames."""

    def __init__(self, monitor: int = 0, max_width: int = 1280, fps: int = 24, backend: str = "auto"):
        self.monitors, self.virtual = list_monitors()
        self.monitor = min(monitor, len(self.monitors) - 1)
        self.max_width, self.fps, self.backend_pref = max_width, fps, backend
        self.backend = None
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.captured = 0
        self.restart_flag = threading.Event()

    # settings may change at runtime
    def configure(self, monitor=None, max_width=None, fps=None):
        if max_width:
            self.max_width = int(max_width)
        if fps:
            self.fps = int(fps)
        if monitor is not None and monitor != self.monitor and 0 <= monitor < len(self.monitors):
            self.monitor = monitor
            self.restart_flag.set()

    def current_monitor(self):
        return self.monitors[self.monitor]

    def _open(self):
        mon = self.monitors[self.monitor]
        if self.backend_pref in ("auto", "dxgi"):
            try:
                import dxcam
                cam = dxcam.create(output_idx=self.monitor, output_color="BGR")
                if cam is not None and (cam.width, cam.height) == (mon["width"], mon["height"]):
                    self.backend = "dxgi"
                    return ("dxgi", cam)
                if cam is not None:
                    cam.release()
            except Exception as e:  # noqa
                log.info("DXGI capture unavailable (%s); using GDI", e)
        import mss
        self.backend = "gdi"
        return ("gdi", mss.MSS())

    def _grab(self, kind, h):
        mon = self.monitors[self.monitor]
        if kind == "dxgi":
            return h.grab()  # None if screen unchanged
        shot = h.grab({"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]})
        return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)

    def _to_frame(self, arr):
        h, w = arr.shape[:2]
        fmt = "bgr24" if arr.shape[2] == 3 else "bgra"
        vf = av.VideoFrame.from_ndarray(np.ascontiguousarray(arr), format=fmt)
        tw = min(self.max_width, w)
        tw -= tw % 2
        th = int(h * tw / w)
        th -= th % 2
        return vf.reformat(width=tw, height=th, format="yuv420p")

    def start(self):
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    def _run(self):
        kind, h = self._open()
        log.info("capture backend=%s monitor=%d", kind, self.monitor)
        last = None
        while not self._stop.is_set():
            t0 = time.monotonic()
            if self.restart_flag.is_set():
                self.restart_flag.clear()
                self._close(kind, h)
                kind, h = self._open()
                last = None
            try:
                arr = self._grab(kind, h)
            except Exception as e:  # display change / lost duplication
                log.warning("grab failed: %s; reopening", e)
                time.sleep(0.5)
                self._close(kind, h)
                self.monitors, self.virtual = list_monitors()
                self.monitor = min(self.monitor, len(self.monitors) - 1)
                kind, h = self._open()
                continue
            if arr is not None:
                last = self._to_frame(arr)
                with self._lock:
                    self._frame = last
                    self.captured += 1
            elif last is not None and self._frame is not None:
                pass  # unchanged
            dt = time.monotonic() - t0
            time.sleep(max(0.0, 1.0 / max(1, self.fps) - dt))
        self._close(kind, h)

    @staticmethod
    def _close(kind, h):
        try:
            if kind == "dxgi":
                h.release()
            else:
                h.close()
        except Exception:
            pass

    def latest(self):
        with self._lock:
            return self._frame


class DesktopTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, source: ScreenSource):
        super().__init__()
        self.src = source
        self._start = None
        self._n = 0
        self.sent = 0

    async def recv(self):
        if self._start is None:
            self._start = time.monotonic()
        interval = 1.0 / max(1, self.src.fps)
        self._n += 1
        wait = self._start + self._n * interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        elif wait < -1:  # fell far behind; resync
            self._start, self._n = time.monotonic(), 0
        frame = self.src.latest()
        while frame is None:
            await asyncio.sleep(0.02)
            frame = self.src.latest()
        out = frame.reformat(format="yuv420p")  # may return same object; pts is set per send
        out.pts = int((time.monotonic() - self._start) * VIDEO_CLOCK)
        out.time_base = fractions.Fraction(1, VIDEO_CLOCK)
        self.sent += 1
        return out
