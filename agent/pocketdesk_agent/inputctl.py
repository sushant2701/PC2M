"""Remote input injection via Win32 SendInput. All incoming messages are validated here."""
import ctypes
import math
import sys
from ctypes import wintypes

IS_WIN = sys.platform == "win32"

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x1, 0x2, 0x4
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x8, 0x10
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x20, 0x40
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x800, 0x1000
MOUSEEVENTF_VIRTUALDESK, MOUSEEVENTF_ABSOLUTE = 0x4000, 0x8000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
WHEEL_DELTA = 120

if IS_WIN:
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]


# --- key table: DOM-style code -> (virtual key, extended?) ---
def _build_keys():
    k = {}
    for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        k["Key" + ch] = (0x41 + i, False)
    for i in range(10):
        k[f"Digit{i}"] = (0x30 + i, False)
        k[f"Numpad{i}"] = (0x60 + i, False)
    for i in range(1, 13):
        k[f"F{i}"] = (0x6F + i, False)
    k.update({
        "Enter": (0x0D, False), "NumpadEnter": (0x0D, True), "Escape": (0x1B, False), "Backspace": (0x08, False),
        "Tab": (0x09, False), "Space": (0x20, False), "Minus": (0xBD, False), "Equal": (0xBB, False),
        "BracketLeft": (0xDB, False), "BracketRight": (0xDD, False), "Backslash": (0xDC, False),
        "Semicolon": (0xBA, False), "Quote": (0xDE, False), "Backquote": (0xC0, False), "Comma": (0xBC, False),
        "Period": (0xBE, False), "Slash": (0xBF, False), "CapsLock": (0x14, False),
        "ShiftLeft": (0xA0, False), "ShiftRight": (0xA1, False), "ControlLeft": (0xA2, False),
        "ControlRight": (0xA3, True), "AltLeft": (0xA4, False), "AltRight": (0xA5, True),
        "MetaLeft": (0x5B, True), "MetaRight": (0x5C, True), "ContextMenu": (0x5D, True),
        "ArrowLeft": (0x25, True), "ArrowUp": (0x26, True), "ArrowRight": (0x27, True), "ArrowDown": (0x28, True),
        "Home": (0x24, True), "End": (0x23, True), "PageUp": (0x21, True), "PageDown": (0x22, True),
        "Insert": (0x2D, True), "Delete": (0x2E, True), "PrintScreen": (0x2C, True), "NumLock": (0x90, True),
        "ScrollLock": (0x91, False), "Pause": (0x13, False), "NumpadAdd": (0x6B, False),
        "NumpadSubtract": (0x6D, False), "NumpadMultiply": (0x6A, False), "NumpadDivide": (0x6F, True),
        "NumpadDecimal": (0x6E, False), "VolumeUp": (0xAF, False), "VolumeDown": (0xAE, False),
        "VolumeMute": (0xAD, False), "MediaPlayPause": (0xB3, False),
    })
    return k


KEYS = _build_keys()
BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


# --- pure coordinate maths (unit tested) ---
def norm_to_pixel(x: float, y: float, mon: dict):
    """Normalized 0..1 within a monitor -> absolute virtual-desktop pixel."""
    x = min(1.0, max(0.0, float(x)))
    y = min(1.0, max(0.0, float(y)))
    px = mon["left"] + round(x * (mon["width"] - 1))
    py = mon["top"] + round(y * (mon["height"] - 1))
    return px, py


def pixel_to_abs(px: int, py: int, virt: dict):
    """Virtual-desktop pixel -> SendInput absolute coords (0..65535 across the virtual desktop)."""
    ax = round((px - virt["left"]) * 65535 / max(1, virt["width"] - 1))
    ay = round((py - virt["top"]) * 65535 / max(1, virt["height"] - 1))
    return ax, ay


def pixel_to_norm(px: int, py: int, mon: dict):
    return ((px - mon["left"]) / max(1, mon["width"] - 1), (py - mon["top"]) / max(1, mon["height"] - 1))


def _num(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError("bad number")
    return min(hi, max(lo, float(v)))


class InputController:
    def __init__(self, get_monitor, get_virtual):
        """get_monitor() -> dict(left,top,width,height) of the selected monitor; get_virtual() -> virtual desktop rect."""
        self.get_monitor, self.get_virtual = get_monitor, get_virtual
        self.down_keys: set[str] = set()
        self.down_btns: set[str] = set()
        self._send = self._send_win if IS_WIN else (lambda *a: None)

    # ---- low-level ----
    def _send_win(self, *inputs):
        n = len(inputs)
        arr = (INPUT * n)(*inputs)
        sent = ctypes.windll.user32.SendInput(n, arr, ctypes.sizeof(INPUT))
        return sent == n

    def _mouse(self, flags, dx=0, dy=0, data=0):
        i = INPUT(type=INPUT_MOUSE)
        i.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
        return self._send(i)

    def _key(self, vk, up, ext, scan=0, uni=False):
        i = INPUT(type=INPUT_KEYBOARD)
        fl = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if ext else 0) | (KEYEVENTF_UNICODE if uni else 0)
        if IS_WIN and not uni:
            scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
        i.ki = KEYBDINPUT(0 if uni else vk, scan, fl, 0, 0)
        return self._send(i)

    # ---- actions ----
    def move_abs(self, nx, ny):
        px, py = norm_to_pixel(nx, ny, self.get_monitor())
        ax, ay = pixel_to_abs(px, py, self.get_virtual())
        self._mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)

    def move_rel(self, dx, dy):
        """Relative move without Windows pointer acceleration (phone applies its own gain):
        read the cursor, add the delta, inject as an absolute position clamped to the virtual desktop."""
        v = self.get_virtual()
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        px = min(v["left"] + v["width"] - 1, max(v["left"], pt.x + int(dx)))
        py = min(v["top"] + v["height"] - 1, max(v["top"], pt.y + int(dy)))
        ax, ay = pixel_to_abs(px, py, v)
        self._mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)

    def button(self, name, down):
        if name not in BUTTONS:
            raise ValueError("bad button")
        self._mouse(BUTTONS[name][0 if down else 1])
        (self.down_btns.add if down else self.down_btns.discard)(name)

    def wheel(self, dx, dy):
        if dy:
            self._mouse(MOUSEEVENTF_WHEEL, data=int(dy * WHEEL_DELTA))
        if dx:
            self._mouse(MOUSEEVENTF_HWHEEL, data=int(dx * WHEEL_DELTA))

    def key(self, code, down):
        if code not in KEYS:
            raise ValueError("unknown key")
        vk, ext = KEYS[code]
        self._key(vk, not down, ext)
        (self.down_keys.add if down else self.down_keys.discard)(code)

    def text(self, s):
        data = s.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            self._key(0, False, False, scan=unit, uni=True)
            self._key(0, True, False, scan=unit, uni=True)

    def release_all(self):
        for b in list(self.down_btns):
            self.button(b, False)
        for k in list(self.down_keys):
            self.key(k, False)

    def cursor_norm(self):
        if not IS_WIN:
            return 0.0, 0.0
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        nx, ny = pixel_to_norm(pt.x, pt.y, self.get_monitor())
        return min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny))

    # ---- message dispatch (validated) ----
    def handle(self, m: dict) -> bool:
        """Apply one input message. Returns True if handled; raises ValueError on invalid input."""
        t = m.get("t")
        if t == "mm":
            self.move_abs(_num(m["x"], 0, 1), _num(m["y"], 0, 1))
        elif t == "mr":
            self.move_rel(_num(m["dx"], -4000, 4000), _num(m["dy"], -4000, 4000))
        elif t == "mb":
            self.button(m["b"], bool(m["d"]) if isinstance(m["d"], bool) else _bad())
        elif t == "ws":
            self.wheel(_num(m.get("dx", 0), -50, 50), _num(m.get("dy", 0), -50, 50))
        elif t == "k":
            if not isinstance(m["c"], str) or not isinstance(m["d"], bool):
                raise ValueError("bad key")
            self.key(m["c"], m["d"])
        elif t == "tx":
            s = m["s"]
            if not isinstance(s, str) or len(s) > 512:
                raise ValueError("bad text")
            self.text(s)
        else:
            return False
        return True


def _bad():
    raise ValueError("bad value")
