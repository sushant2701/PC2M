"""PocketDesk signaling service (REST + WebSocket relay). Never sees media or the pair secret."""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .db import DB
from .ratelimit import RateLimiter

log = logging.getLogger("pocketdesk.signaling")
LOOKUP_RE = re.compile(r"^[A-Z2-7]{6}$")
MAX_WS_MSG = 64 * 1024
PAIR_TTL = 300


class RegisterReq(BaseModel):
    name: str


class CodeReq(BaseModel):
    lookup: str


class ClaimReq(BaseModel):
    code: str
    device_name: str
    proof: str


def create_app(db_path: str = None, stun_urls=None, turn_urls=None, turn_secret=None,
               trust_proxy: bool = False, register_key: str = None) -> FastAPI:
    db = DB(db_path or os.environ.get("POCKETDESK_DB", "pocketdesk.db"))
    stun_urls = stun_urls if stun_urls is not None else [u for u in os.environ.get("STUN_URLS", "stun:stun.l.google.com:19302").split(",") if u]
    turn_urls = turn_urls if turn_urls is not None else [u for u in os.environ.get("TURN_URLS", "").split(",") if u]
    turn_secret = turn_secret or os.environ.get("TURN_SECRET")
    register_key = register_key or os.environ.get("REGISTER_KEY")  # optional: restrict who can register agents
    app = FastAPI(title="PocketDesk Signaling", docs_url=None, redoc_url=None)
    app.state.db = db
    agents_ws: dict[str, WebSocket] = {}
    devices_ws: dict[str, WebSocket] = {}
    app.state.agents_ws, app.state.devices_ws = agents_ws, devices_ws
    rl_register = RateLimiter(10, 3600)
    rl_claim = RateLimiter(10, 60)
    rl_claim_global = RateLimiter(100, 60)
    rl_auth_fail = RateLimiter(10, 60)
    rl_code = RateLimiter(10, 60)

    def ip_of(request_or_ws) -> str:
        if trust_proxy:
            xf = request_or_ws.headers.get("x-forwarded-for")
            if xf:
                return xf.split(",")[0].strip()
        return request_or_ws.client.host if request_or_ws.client else "?"

    def ice_servers(identity: str):
        servers = [{"urls": stun_urls}] if stun_urls else []
        if turn_urls and turn_secret:
            exp = int(time.time()) + 3600
            user = f"{exp}:{identity}"
            cred = base64.b64encode(hmac.new(turn_secret.encode(), user.encode(), hashlib.sha1).digest()).decode()
            servers.append({"urls": turn_urls, "username": user, "credential": cred})
        return servers

    def bearer(authorization: str, ip: str):
        if not authorization or not authorization.startswith("Bearer ") or ":" not in authorization[7:]:
            raise HTTPException(401, "missing credentials")
        ident, secret = authorization[7:].split(":", 1)
        return ident, secret

    def auth_agent(authorization: str, request: Request):
        ip = ip_of(request)
        ident, secret = bearer(authorization, ip)
        a = db.auth_agent(ident, secret)
        if not a:
            if not rl_auth_fail.allow(ip):
                raise HTTPException(429, "too many attempts")
            raise HTTPException(401, "invalid credentials")
        return a

    def auth_device(authorization: str, request: Request):
        ip = ip_of(request)
        ident, token = bearer(authorization, ip)
        d = db.auth_device(ident, token)
        if not d:
            if not rl_auth_fail.allow(ip):
                raise HTTPException(429, "too many attempts")
            raise HTTPException(401, "invalid credentials")
        return d

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/api/agents/register")
    def register(req: RegisterReq, request: Request, x_register_key: str = Header(default=None)):
        if register_key and not (x_register_key and hmac.compare_digest(x_register_key, register_key)):
            raise HTTPException(403, "registration key required")
        if not rl_register.allow(ip_of(request)):
            raise HTTPException(429, "too many registrations")
        aid, secret = db.create_agent(req.name or "PC")
        log.info("agent registered %s", aid)
        return {"agent_id": aid, "agent_secret": secret}

    @app.post("/api/agents/pair-code")
    def pair_code(req: CodeReq, request: Request, authorization: str = Header(default=None)):
        a = auth_agent(authorization, request)
        if not LOOKUP_RE.match(req.lookup):
            raise HTTPException(400, "bad code format")
        if not rl_code.allow(a["id"]):
            raise HTTPException(429, "slow down")
        if not db.add_code(a["id"], req.lookup, PAIR_TTL):
            raise HTTPException(409, "code collision, retry")
        return {"expires_in": PAIR_TTL}

    @app.post("/api/pair/claim")
    async def claim(req: ClaimReq, request: Request):
        ip = ip_of(request)
        if not rl_claim.allow(ip) or not rl_claim_global.allow("all"):
            log.warning("pair claim rate-limited ip=%s", ip)
            raise HTTPException(429, "too many attempts")
        lookup = re.sub(r"[\s-]", "", req.code).upper()[:6]
        if not LOOKUP_RE.match(lookup) or not (1 <= len(req.device_name) <= 64) or len(req.proof) != 64:
            raise HTTPException(400, "invalid request")
        row = db.consume_code(lookup)
        if not row:
            log.warning("pair claim failed ip=%s", ip)
            raise HTTPException(404, "invalid or expired code")
        agent_ws = agents_ws.get(row["agent_id"])
        if not agent_ws:
            raise HTTPException(409, "PC is offline")
        did, token = db.create_device(row["agent_id"], req.device_name)
        await agent_ws.send_text(json.dumps({"type": "paired", "device_id": did, "device_name": req.device_name,
                                             "lookup": lookup, "proof": req.proof}))
        agent = db.get_agent(row["agent_id"])
        log.info("device %s paired with %s", did, row["agent_id"])
        return {"device_id": did, "device_token": token, "agent_id": agent["id"], "agent_name": agent["name"]}

    @app.get("/api/status")
    def status(request: Request, authorization: str = Header(default=None)):
        d = auth_device(authorization, request)
        a = db.get_agent(d["agent_id"])
        return {"agent_id": a["id"], "agent_name": a["name"], "online": a["id"] in agents_ws}

    @app.get("/api/devices")
    def list_devices(request: Request, authorization: str = Header(default=None)):
        a = auth_agent(authorization, request)
        return {"devices": db.list_devices(a["id"])}

    @app.delete("/api/devices/{device_id}")
    async def revoke(device_id: str, request: Request, authorization: str = Header(default=None)):
        ident = (authorization or "")[7:].split(":", 1)[0]
        if ident.startswith("a_"):
            a = auth_agent(authorization, request)
            dev = db.get_device(device_id)
            if not dev or dev["agent_id"] != a["id"]:
                raise HTTPException(404, "no such device")
        else:
            d = auth_device(authorization, request)
            if d["id"] != device_id:
                raise HTTPException(403, "forbidden")
            dev = d
        db.revoke_device(device_id)
        ws = devices_ws.pop(device_id, None)
        if ws:
            try:
                await ws.close(code=4403)
            except Exception:
                pass
        aws = agents_ws.get(dev["agent_id"])
        if aws:
            try:
                await aws.send_text(json.dumps({"type": "device_revoked", "device_id": device_id}))
            except Exception:
                pass
        log.info("device %s revoked", device_id)
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        ip = ip_of(ws)
        role = ident = None
        try:
            first = json.loads(await asyncio.wait_for(ws.receive_text(), 10))
            if first.get("type") != "auth":
                raise ValueError("auth required")
            rid, secret = str(first.get("id", "")), str(first.get("secret", ""))
            if first.get("role") == "agent":
                ok = db.auth_agent(rid, secret)
            elif first.get("role") == "device":
                ok = db.auth_device(rid, secret)
            else:
                ok = None
            if not ok:
                if not rl_auth_fail.allow(ip):
                    log.warning("ws auth brute force ip=%s", ip)
                await ws.send_text(json.dumps({"type": "error", "error": "auth"}))
                await ws.close(code=4401)
                return
            role, ident = first["role"], rid
            table = agents_ws if role == "agent" else devices_ws
            old = table.get(ident)
            table[ident] = ws
            if old:
                try:
                    await old.close(code=4409)
                except Exception:
                    pass
            await ws.send_text(json.dumps({"type": "ready", "ice_servers": ice_servers(ident)}))
            if role == "device":
                dev = db.get_device(ident)
                await ws.send_text(json.dumps({"type": "presence", "online": dev["agent_id"] in agents_ws}))
            else:
                for did, dws in list(devices_ws.items()):
                    d = db.get_device(did)
                    if d and d["agent_id"] == ident:
                        try:
                            await dws.send_text(json.dumps({"type": "presence", "online": True}))
                        except Exception:
                            pass
            while True:
                raw = await ws.receive_text()
                if len(raw) > MAX_WS_MSG:
                    await ws.close(code=1009)
                    return
                msg = json.loads(raw)
                t = msg.get("type")
                if role == "device":
                    dev = db.auth_device(ident, secret)  # re-check revocation on each message
                    if not dev:
                        await ws.close(code=4403)
                        return
                    target = agents_ws.get(dev["agent_id"])
                    if t in ("offer", "bye"):
                        if not target:
                            await ws.send_text(json.dumps({"type": "agent_offline", "session_id": msg.get("session_id")}))
                            continue
                        msg["device_id"] = ident
                        msg.pop("agent_id", None)
                        await target.send_text(json.dumps(msg))
                    elif t == "ping":
                        await ws.send_text(json.dumps({"type": "pong"}))
                elif role == "agent":
                    if t in ("answer", "bye", "error"):
                        tdev = devices_ws.get(str(msg.get("device_id")))
                        d = db.get_device(str(msg.get("device_id")))
                        if tdev and d and d["agent_id"] == ident and not d["revoked"]:
                            await tdev.send_text(json.dumps(msg))
                    elif t == "revoke":
                        d = db.get_device(str(msg.get("device_id")))
                        if d and d["agent_id"] == ident:
                            db.revoke_device(d["id"])
                            w = devices_ws.pop(d["id"], None)
                            if w:
                                await w.close(code=4403)
                    elif t == "ping":
                        await ws.send_text(json.dumps({"type": "pong"}))
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, json.JSONDecodeError, RuntimeError):
            pass
        finally:
            if ident:
                table = agents_ws if role == "agent" else devices_ws
                if table.get(ident) is ws:
                    del table[ident]
                if role == "agent":
                    for did, dws in list(devices_ws.items()):
                        d = db.get_device(did)
                        if d and d["agent_id"] == ident:
                            try:
                                await dws.send_text(json.dumps({"type": "presence", "online": False}))
                            except Exception:
                                pass

    return app


def main():
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(create_app(trust_proxy=os.environ.get("TRUST_PROXY") == "1"), host=host,
                port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
