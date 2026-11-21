"""Pairing crypto shared (by spec) with the mobile app. See ARCHITECTURE.md 'Protocol'."""
import base64
import hashlib
import hmac
import re
import secrets

B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
SALT = b"pocketdesk-pair-v1"


def new_pairing_code():
    """Returns (lookup, secret_bytes, display_string)."""
    lookup = "".join(secrets.choice(B32) for _ in range(6))
    secret = secrets.token_bytes(10)  # 80 bits -> 16 base32 chars
    s32 = base64.b32encode(secret).decode()
    disp = lookup + "-" + "-".join(s32[i:i + 4] for i in range(0, 16, 4))
    return lookup, secret, disp


def parse_pairing_code(text: str):
    """Returns (lookup, secret_bytes) or raises ValueError."""
    t = re.sub(r"[\s-]", "", text).upper()
    if len(t) != 22 or any(ch not in B32 for ch in t):
        raise ValueError("invalid pairing code")
    return t[:6], base64.b32decode(t[6:])


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]


def derive_pair_key(secret: bytes) -> bytes:
    return hkdf_sha256(secret, SALT, b"pair-key", 32)


def _mac(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def claim_proof(key: bytes, lookup: str, device_name: str) -> str:
    return _mac(key, f"pd1|claim|{lookup}|{device_name}")


def sdp_fingerprint(sdp: str) -> str:
    m = re.search(r"^a=fingerprint:\S+\s+([0-9A-Fa-f:]+)\s*$", sdp, re.M)
    if not m:
        raise ValueError("no DTLS fingerprint in SDP")
    return m.group(1).lower()


def offer_mac(key: bytes, session_id: str, device_id: str, ts: int, sdp: str) -> str:
    return _mac(key, f"pd1|offer|{session_id}|{device_id}|{ts}|{sdp_fingerprint(sdp)}")


def answer_mac(key: bytes, session_id: str, device_id: str, ts: int, sdp: str) -> str:
    return _mac(key, f"pd1|answer|{session_id}|{device_id}|{ts}|{sdp_fingerprint(sdp)}")


def relay_mac(key: bytes, session_id: str, device_id: str, ts: int) -> str:
    return _mac(key, f"pd1|relay|{session_id}|{device_id}|{ts}")


def relay_ok_mac(key: bytes, session_id: str, device_id: str, ts: int) -> str:
    return _mac(key, f"pd1|relayok|{session_id}|{device_id}|{ts}")


def verify(expected_hex: str, given_hex: str) -> bool:
    return hmac.compare_digest(expected_hex, str(given_hex))
