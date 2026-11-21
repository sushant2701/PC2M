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


def lock_workstation():
    ctypes.windll.user32.LockWorkStation()
