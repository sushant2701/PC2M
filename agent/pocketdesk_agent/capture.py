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
        self.roi, self.roi_gen = None, 0
        self._raw, self._reframe = None, False
        self.restart_flag = threading.Event()

    # settings may change at runtime
    def configure(self, monitor=None, max_width=None, fps=None):
        if max_width:
            if int(max_width) != self.max_width:
                self._reframe = True
            self.max_width = int(max_width)
        if fps:
            self.fps = int(fps)
        if monitor is not None and monitor != self.monitor and 0 <= monitor < len(self.monitors):
            self.monitor = monitor
            self.roi = None
            self.restart_flag.set()

    def current_monitor(self):
        return self.monitors[self.monitor]

    def _open(self):
        mon = self.monitors[self.monitor]
        if self.backend_pref in ("auto", "dxgi"):
            try:
                import dxcam
                cam = dxcam.create(output_idx=self.monitor, output_color="BGR", processor_backend="numpy")
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

    # ---- zoom support: send only the region the phone is looking at, cut from the full-resolution screen ----
    def set_roi(self, roi):
        """roi = (x, y, w, h) normalized to the monitor, or None for the whole screen."""
        self.roi = roi
        if roi:
            self.roi_gen += 1
        self._reframe = True

    def _out_size(self, w, h):
        """Output frame size for a full-resolution screen of w x h. With a region of interest the width carries a small
        per-request offset (-2 px steps) so the phone can tell exactly which request a received frame belongs to."""
        if self.roi:
            cw, ch = max(2, int(self.roi[2] * w)), max(2, int(self.roi[3] * h))
            tw = min(cw, max(self.max_width, 1100)) - 2 * (self.roi_gen % 8)
            tw = max(320, tw)
        else:
            cw, ch, tw = w, h, min(self.max_width, w)
        tw -= tw % 2
        th = int(ch * tw / cw)
        th -= th % 2
        return tw, max(2, th)

    def _to_frame(self, arr):
        h, w = arr.shape[:2]
        roi = self.roi
        tw, th = self._out_size(w, h)
        if roi:
            x0, y0 = int(roi[0] * w), int(roi[1] * h)
            arr = arr[y0:min(h, y0 + max(2, int(roi[3] * h))), x0:min(w, x0 + max(2, int(roi[2] * w)))]
        fmt = "bgr24" if arr.shape[2] == 3 else "bgra"
        vf = av.VideoFrame.from_ndarray(np.ascontiguousarray(arr), format=fmt)
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
                last, self._raw = None, None
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
            if arr is None and self._reframe and self._raw is not None:
                arr = self._raw  # screen unchanged but the requested region/size changed: re-cut the last full-resolution capture
            if arr is not None:
                self._raw, self._reframe = arr, False
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
