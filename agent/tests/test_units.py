import asyncio

import pytest
from pocketdesk_agent import crypto
from pocketdesk_agent.inputctl import InputController, norm_to_pixel, pixel_to_abs, pixel_to_norm, KEYS

MON = {"left": 1920, "top": 100, "width": 2560, "height": 1440}
VIRT = {"left": 0, "top": 0, "width": 4480, "height": 1540}


def test_hkdf_rfc5869_vector():
    ikm = bytes.fromhex("0b" * 22)
    salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    okm = crypto.hkdf_sha256(ikm, salt, info, 42)
    assert okm.hex() == "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"


def test_pairing_code_roundtrip():
    lookup, secret, disp = crypto.new_pairing_code()
    l2, s2 = crypto.parse_pairing_code(disp.lower().replace("-", " "))
    assert (l2, s2) == (lookup, secret) and len(disp) == 6 + 4 + 4 * 4
    with pytest.raises(ValueError):
        crypto.parse_pairing_code("short")


def test_mac_bound_to_fingerprint():
    key = crypto.derive_pair_key(b"0123456789")
    sdp1 = "v=0\r\na=fingerprint:sha-256 AA:BB:CC\r\n"
    sdp2 = "v=0\r\na=fingerprint:sha-256 AA:BB:CD\r\n"
    m1 = crypto.offer_mac(key, "s", "d", 5, sdp1)
    assert crypto.verify(m1, crypto.offer_mac(key, "s", "d", 5, sdp1.replace("AA:BB:CC", "aa:bb:cc")))
    assert not crypto.verify(m1, crypto.offer_mac(key, "s", "d", 5, sdp2))
    assert not crypto.verify(m1, crypto.offer_mac(key, "s2", "d", 5, sdp1))
    assert crypto.answer_mac(key, "s", "d", 5, sdp1) != m1  # offer/answer domain separated
    with pytest.raises(ValueError):
        crypto.sdp_fingerprint("v=0")


def test_coordinate_mapping_corners_and_center():
    assert norm_to_pixel(0, 0, MON) == (1920, 100)
    assert norm_to_pixel(1, 1, MON) == (1920 + 2559, 100 + 1439)
    assert norm_to_pixel(0.5, 0.5, MON) == (1920 + round(0.5 * 2559), 100 + round(0.5 * 1439))
    assert norm_to_pixel(-5, 9, MON) == (1920, 100 + 1439)  # clamped
    assert pixel_to_abs(0, 0, VIRT) == (0, 0)
    assert pixel_to_abs(4479, 1539, VIRT) == (65535, 65535)


def test_roundtrip_pixel_error_below_one_pixel():
    for nx in (0, 0.1, 0.33, 0.77, 1):
        for ny in (0, 0.5, 1):
            px, py = norm_to_pixel(nx, ny, MON)
            bx, by = pixel_to_norm(px, py, MON)
            assert abs(bx - nx) <= 1 / 2559 and abs(by - ny) <= 1 / 1439
    # abs coords -> pixel via Windows' mapping floor((abs*W)/65536) stays within 1px
    px, py = norm_to_pixel(0.5, 0.5, MON)
    ax, ay = pixel_to_abs(px, py, VIRT)
    assert abs(ax * VIRT["width"] / 65536 - px) < 1.5


class Rec(InputController):
    def __init__(self):
        super().__init__(lambda: MON, lambda: VIRT)
        self.calls = []
        self._send = lambda *a: self.calls.append(a) or True


def test_validation_rejects_bad_messages():
    r = Rec()
    for bad in [{"t": "mm", "x": "a", "y": 0}, {"t": "mm", "x": float("nan"), "y": 0}, {"t": "mb", "b": "x", "d": True},
                {"t": "mb", "b": "left", "d": 1}, {"t": "k", "c": "NotAKey", "d": True}, {"t": "k", "c": "KeyA", "d": "yes"},
                {"t": "tx", "s": "x" * 600}, {"t": "mm", "x": True, "y": 0}, {"t": "mm"}]:
        with pytest.raises((ValueError, KeyError)):
            r.handle(bad)
    assert r.handle({"t": "unknown"}) is False
    assert r.calls == []


def test_release_all_on_disconnect():
    r = Rec()
    r.handle({"t": "mb", "b": "left", "d": True})
    r.handle({"t": "k", "c": "ControlLeft", "d": True})
    assert r.down_btns == {"left"} and r.down_keys == {"ControlLeft"}
    r.release_all()
    assert not r.down_btns and not r.down_keys


@pytest.mark.asyncio
async def test_rate_limit_and_signal_loss_release():
    import time
    from pocketdesk_agent import session as S

    class FakeSrc:
        monitors = [MON]
        virtual = VIRT
        monitor = 0
        backend = "x"
        def current_monitor(self): return MON
        def configure(self, **k): pass

    class H(S.ControlHandler):
        device_name = "t"
        closed = False
        def __init__(self):
            self._init_control(FakeSrc())
            self.input._send = lambda *a: True
            self.sent = []
        def _send(self, o): self.sent.append(o)
        async def close(self, reason=""): self.closed = True

    h = H()
    # a burst far above the limit is mostly dropped, not executed
    for _ in range(5000):
        h._on_message('{"t":"mr","dx":1,"dy":1}')
    await asyncio.sleep(0)
    assert h.closed, "sustained flood must end the session"
    # dead-man: held key is released when the signal goes quiet
    h2 = H()
    h2._on_message('{"t":"k","c":"ControlLeft","d":true}')
    assert h2.input.down_keys == {"ControlLeft"}
    h2.last_rx = time.monotonic() - 10
    h2._guard_signal_loss()
    assert not h2.input.down_keys
    # unknown / malformed messages count as bad and end the session after BAD_LIMIT
    h3 = H()
    for _ in range(S.BAD_LIMIT + 2):
        h3._on_message('{"t":"nope"}')
    await asyncio.sleep(0)
    assert h3.closed
    # after close nothing is executed
    h3.input.down_keys.clear()
    h3._on_message('{"t":"k","c":"KeyA","d":true}')
    assert not h3.input.down_keys


def test_lock_detection_and_awake_do_not_crash():
    from pocketdesk_agent.system import is_locked, set_awake
    assert is_locked() is False  # tests run in an unlocked interactive session
    set_awake(True)
    set_awake(False)


def test_text_emits_unicode_pairs_and_keytable():
    r = Rec()
    r.handle({"t": "tx", "s": "a\U0001F600"})
    assert len(r.calls) == 2 * 3  # a + surrogate pair, down+up each
    for k in ("KeyA", "Enter", "ControlLeft", "F12", "ArrowUp", "MetaLeft", "Digit9"):
        assert k in KEYS
