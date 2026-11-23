"""PocketDesk agent CLI. `pocketdesk-agent` (no args) opens the GUI."""
import argparse
import asyncio
import logging
import logging.handlers
import sys

from .config import Config, data_dir

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def setup_logging(verbose=False):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    h = logging.handlers.RotatingFileHandler(data_dir() / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(h)
    if sys.stderr:
        s = logging.StreamHandler()
        s.setFormatter(fmt)
        root.addHandler(s)
    logging.getLogger("aiortc").setLevel(logging.WARNING)
    logging.getLogger("aioice").setLevel(logging.WARNING)


def set_autostart(enable: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" -m pocketdesk_agent'
            winreg.SetValueEx(k, "PocketDeskAgent", 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(k, "PocketDeskAgent")
            except FileNotFoundError:
                pass


def pairing_link(cfg, code: str) -> str:
    """Link/QR content: phone opens the web client and pairs. The code is in the URL fragment (never sent to a server)."""
    server = current_public_url(cfg)
    n = f"&n={cfg['ntfy_topic']}" if cfg["tunnel"] and cfg["ntfy_topic"] else ""  # lets the app follow address changes
    if cfg["web_url"]:  # web client hosted elsewhere (e.g. Vercel): tell it which signaling server to use
        return f"{cfg['web_url'].rstrip('/')}/#c={code}&s={server}{n}"
    return f"{server}/#c={code}{n}"


def current_public_url(cfg) -> str:
    """Address the phone should use: the tunnel supervisor's live address if present, else config, else the server URL."""
    try:
        t = (data_dir() / "public_url.txt").read_text().strip()
        if t.startswith("https://"):
            return t.rstrip("/")
    except OSError:
        pass
    if cfg["tunnel"]:  # tunnel enabled but not up right now: never hand out a localhost link
        return "https://waiting-for-tunnel.invalid"
    return (cfg["public_url"] or cfg["server_url"]).rstrip("/")


def selftest() -> str:
    """Checks the pieces that commonly break on a new machine / in the packaged exe."""
    import time
    lines = []

    def step(name, fn):
        try:
            lines.append(f"PASS {name}: {fn()}")
        except Exception as e:  # noqa
            lines.append(f"FAIL {name}: {e!r}")

    def cap():
        from .capture import ScreenSource, set_dpi_aware
        set_dpi_aware()
        s = ScreenSource(max_width=640, fps=10)
        s.start()
        t = time.time()
        while s.latest() is None and time.time() - t < 5:
            time.sleep(0.1)
        f = s.latest()
        s.stop()
        return f"backend={s.backend} monitors={len(s.monitors)} frame={f.width}x{f.height}"

    def enc():
        import av
        import numpy as np
        c = av.CodecContext.create("libvpx", "w")
        c.width, c.height, c.pix_fmt = 320, 240, "yuv420p"
        c.time_base = __import__("fractions").Fraction(1, 30)
        c.open()
        f = av.VideoFrame.from_ndarray(np.zeros((240, 320, 3), np.uint8), format="rgb24").reformat(format="yuv420p")
        f.pts = 0
        return f"VP8 encoder ok ({len(c.encode(f))} packets)"

    def dp():
        from . import config
        assert config._unprotect(config._protect(b"x")) == b"x"
        return "DPAPI ok"

    def rtc():
        import aiortc
        from .crypto import derive_pair_key
        return f"aiortc {aiortc.__version__}, key len {len(derive_pair_key(b'0123456789'))}"
    for n, f in (("capture", cap), ("vp8-encoder", enc), ("dpapi", dp), ("webrtc", rtc)):
        step(n, f)
    return "\n".join(lines)


async def headless(cfg, pair):
    from .agent import Agent
    def emit(k, d=None):
        try:
            print(f"[{k}] {d}", flush=True)
        except OSError:  # stdout closed by parent; logging continues in agent.log
            pass
    ag = Agent(cfg, emit)
    task = asyncio.ensure_future(ag.run())
    if pair:
        await asyncio.sleep(2)
        code = await ag.start_pairing()
        print("PAIRING CODE:", code, flush=True)
        print("PAIRING LINK:", pairing_link(cfg, code), flush=True)
    try:
        await task
    except asyncio.CancelledError:
        pass


def main(argv=None):
    p = argparse.ArgumentParser(prog="pocketdesk-agent")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("config", help="set server/name")
    c.add_argument("--server")
    c.add_argument("--name")
    c.add_argument("--register-key")
    c.add_argument("--tunnel", choices=["on", "off"], help="run the self-restarting public tunnel inside the agent (ssh -> serveo.net)")
    c.add_argument("--web-url", help="where the phone web client is hosted if not on the server (e.g. https://pocketdesk.vercel.app)")
    c.add_argument("--public-url", help="https address the phone uses (e.g. tunnel URL); used in the pairing QR")
    c.add_argument("--max-width", type=int)
    c.add_argument("--fps", type=int)
    r = sub.add_parser("run", help="run without GUI")
    r.add_argument("--pair", action="store_true", help="print a pairing code after connecting")
    sub.add_parser("devices")
    rv = sub.add_parser("revoke")
    rv.add_argument("device_id")
    st = sub.add_parser("selftest", help="verify capture/encoder/crypto/DPAPI work on this machine")
    st.add_argument("--out", help="write the report to this file")
    a = sub.add_parser("autostart", help="start agent at user logon (opt-in)")
    a.add_argument("state", choices=["on", "off"])
    args = p.parse_args(argv)
    setup_logging(args.verbose)
    cfg = Config()

    if args.cmd == "config":
        from .agent import check_server_url
        if args.server:
            check_server_url(args.server)
            cfg["server_url"] = args.server.rstrip("/")
            cfg["agent_id"] = cfg["agent_secret"] = ""
        for k, v in (("name", args.name), ("register_key", args.register_key), ("public_url", (args.public_url or "").rstrip("/")), ("web_url", (args.web_url or "").rstrip("/")),("max_width", args.max_width), ("fps", args.fps)):
            if v:
                cfg[k] = v
        if args.tunnel:
            cfg["tunnel"] = args.tunnel == "on"
            if cfg["tunnel"]:
                from .tunnel import ensure_topic
                ensure_topic(cfg)
        cfg.save()
        print("saved")
    elif args.cmd == "devices":
        for did, d in cfg["devices"].items():
            print(did, d["name"])
    elif args.cmd == "revoke":
        from .agent import Agent
        asyncio.run(Agent(cfg).revoke_device(args.device_id))
        print("revoked")
    elif args.cmd == "selftest":
        rep = selftest()
        print(rep)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(rep)
    elif args.cmd == "autostart":
        set_autostart(args.state == "on")
        print("autostart", args.state)
    elif args.cmd == "run":
        try:
            asyncio.run(headless(cfg, args.pair))
        except KeyboardInterrupt:
            pass
    else:
        from .ui import AgentUI
        AgentUI(cfg).run()


if __name__ == "__main__":
    main()
