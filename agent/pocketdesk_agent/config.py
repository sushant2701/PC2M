"""Agent configuration + identity. Secrets are DPAPI-protected (current-user scope) on Windows."""
import base64
import json
import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("POCKETDESK_HOME")
    if override:
        p = Path(override)
    else:
        p = Path(os.environ.get("APPDATA", str(Path.home()))) / "PocketDesk"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _protect(raw: bytes) -> bytes:
    if sys.platform == "win32":
        import win32crypt
        return win32crypt.CryptProtectData(raw, "PocketDesk", None, None, None, 0)
    raise RuntimeError("secure storage only implemented for Windows")


def _unprotect(blob: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]


DEFAULTS = {"server_url": "", "agent_id": "", "agent_secret": "", "name": "", "devices": {},
            "register_key": "", "public_url": "", "max_width": 1280, "fps": 24, "autostart": False}


class Config:
    """JSON config; the whole file content is DPAPI-encrypted at rest (contains secrets)."""

    def __init__(self, path: Path = None):
        self.path = path or (data_dir() / "config.bin")
        self.d = dict(DEFAULTS)
        self.load()

    def load(self):
        if self.path.exists():
            raw = _unprotect(base64.b64decode(self.path.read_bytes()))
            self.d.update(json.loads(raw))

    def save(self):
        blob = _protect(json.dumps(self.d).encode())
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(base64.b64encode(blob))
        os.replace(tmp, self.path)

    def __getitem__(self, k):
        return self.d[k]

    def __setitem__(self, k, v):
        self.d[k] = v

    # devices: {device_id: {"name":..., "key": hex}}
    def add_device(self, did: str, name: str, key: bytes):
        self.d["devices"][did] = {"name": name, "key": key.hex()}
        self.save()

    def remove_device(self, did: str):
        self.d["devices"].pop(did, None)
        self.save()

    def device_key(self, did: str):
        e = self.d["devices"].get(did)
        return bytes.fromhex(e["key"]) if e else None
