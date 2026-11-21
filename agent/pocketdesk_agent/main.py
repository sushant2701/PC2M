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


async def headless(cfg, pair):
    from .agent import Agent
    ag = Agent(cfg, lambda k, d=None: print(f"[{k}] {d}", flush=True))
    task = asyncio.ensure_future(ag.run())
    if pair:
        await asyncio.sleep(2)
        print("PAIRING CODE:", await ag.start_pairing(), flush=True)
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
    c.add_argument("--max-width", type=int)
    c.add_argument("--fps", type=int)
    r = sub.add_parser("run", help="run without GUI")
    r.add_argument("--pair", action="store_true", help="print a pairing code after connecting")
    sub.add_parser("devices")
    rv = sub.add_parser("revoke")
    rv.add_argument("device_id")
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
        for k, v in (("name", args.name), ("register_key", args.register_key), ("max_width", args.max_width), ("fps", args.fps)):
            if v:
                cfg[k] = v
        cfg.save()
        print("saved")
    elif args.cmd == "devices":
        for did, d in cfg["devices"].items():
            print(did, d["name"])
    elif args.cmd == "revoke":
        from .agent import Agent
        asyncio.run(Agent(cfg).revoke_device(args.device_id))
        print("revoked")
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
