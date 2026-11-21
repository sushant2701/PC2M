"""Small Windows system helpers (clipboard text, lock). Only invoked on explicit, authenticated user requests."""
import ctypes


def get_clipboard_text():
    import win32clipboard
    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return ""
    finally:
        win32clipboard.CloseClipboard()


def set_clipboard_text(s: str):
    import win32clipboard
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, s)
    finally:
        win32clipboard.CloseClipboard()


def is_locked() -> bool:
    """True when the secure desktop (lock screen / UAC / Ctrl+Alt+Del) is active.
    Windows does not let a normal user-level app capture or control that desktop."""
    try:
        u = ctypes.windll.user32
        u.OpenInputDesktop.restype = ctypes.c_void_p
        h = u.OpenInputDesktop(0, False, 0x0001)
        if not h:
            return True
        u.CloseDesktop(ctypes.c_void_p(h))
        return False
    except Exception:
        return False


ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2


def set_awake(remote_active: bool):
    """While the agent runs: don't let the PC sleep. While a remote session is active: also keep the display on
    (like a video-call app). Does not change any Windows setting; reverts when the process exits."""
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | (ES_DISPLAY_REQUIRED if remote_active else 0)
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def lock_workstation():
    ctypes.windll.user32.LockWorkStation()
