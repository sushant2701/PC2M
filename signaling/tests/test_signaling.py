import json
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pocketdesk_signaling.app import create_app

PROOF = "a" * 64


@pytest.fixture
def env():
    app = create_app(":memory:", stun_urls=["stun:x:1"], turn_urls=["turns:t:443"], turn_secret="s3cret")
    return TestClient(app), app


def mk_agent(c):
    r = c.post("/api/agents/register", json={"name": "PC"}).json()
    return r["agent_id"], r["agent_secret"]


def hdr(i, s):
    return {"Authorization": f"Bearer {i}:{s}"}


def ws_auth(c, role, i, s):
    ws = c.websocket_connect("/ws")
    w = ws.__enter__()
    w.send_text(json.dumps({"type": "auth", "role": role, "id": i, "secret": s}))
    return ws, w


def pair(c, aid, asec, code="ABCDEF"):
    assert c.post("/api/agents/pair-code", json={"lookup": code}, headers=hdr(aid, asec)).status_code == 200
    ws, w = ws_auth(c, "agent", aid, asec)
    assert json.loads(w.receive_text())["type"] == "ready"
    r = c.post("/api/pair/claim", json={"code": code, "device_name": "Phone", "proof": PROOF})
    return ws, w, r


def test_pair_and_status(env):
    c, _ = env
    aid, asec = mk_agent(c)
    ws, w, r = pair(c, aid, asec)
    assert r.status_code == 200
    ev = json.loads(w.receive_text())
    assert ev["type"] == "paired" and ev["proof"] == PROOF and ev["device_id"] == r.json()["device_id"]
    d = r.json()
    s = c.get("/api/status", headers=hdr(d["device_id"], d["device_token"])).json()
    assert s["online"] is True and s["agent_id"] == aid
    ws.__exit__(None, None, None)


def test_code_single_use_and_bad_code(env):
    c, _ = env
    aid, asec = mk_agent(c)
    ws, w, r = pair(c, aid, asec)
    assert r.status_code == 200
    r2 = c.post("/api/pair/claim", json={"code": "ABCDEF", "device_name": "P2", "proof": PROOF})
    assert r2.status_code == 404
    assert c.post("/api/pair/claim", json={"code": "ZZZZZZ", "device_name": "P", "proof": PROOF}).status_code == 404
    ws.__exit__(None, None, None)


def test_claim_rate_limited(env):
    c, _ = env
    codes = [c.post("/api/pair/claim", json={"code": "AAAAAA", "device_name": "P", "proof": PROOF}).status_code for _ in range(12)]
    assert 429 in codes


def test_claim_requires_agent_online(env):
    c, _ = env
    aid, asec = mk_agent(c)
    c.post("/api/agents/pair-code", json={"lookup": "QQQQQQ"}, headers=hdr(aid, asec))
    assert c.post("/api/pair/claim", json={"code": "QQQQQQ", "device_name": "P", "proof": PROOF}).status_code == 409


def test_auth_required(env):
    c, _ = env
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/status", headers=hdr("d_x", "bad")).status_code == 401
    assert c.post("/api/agents/pair-code", json={"lookup": "ABCDEF"}, headers=hdr("a_x", "bad")).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws") as w:
            w.send_text(json.dumps({"type": "auth", "role": "device", "id": "d_x", "secret": "nope"}))
            assert json.loads(w.receive_text())["error"] == "auth"
            w.receive_text()


def test_offer_answer_relay_and_ice(env):
    c, _ = env
    aid, asec = mk_agent(c)
    aws, aw, r = pair(c, aid, asec)
    aw.receive_text()  # paired
    d = r.json()
    dws, dw = ws_auth(c, "device", d["device_id"], d["device_token"])
    ready = json.loads(dw.receive_text())
    assert ready["type"] == "ready"
    turn = [s for s in ready["ice_servers"] if "username" in s][0]
    assert turn["username"].endswith(":" + d["device_id"]) and turn["credential"]
    assert json.loads(dw.receive_text())["online"] is True
    dw.send_text(json.dumps({"type": "offer", "session_id": "s1", "sdp": "v=0", "ts": 1, "mac": "m", "agent_id": "a_spoof"}))
    off = json.loads(aw.receive_text())
    assert off["type"] == "offer" and off["device_id"] == d["device_id"] and "agent_id" not in off
    aw.send_text(json.dumps({"type": "answer", "device_id": d["device_id"], "session_id": "s1", "sdp": "v=0", "mac": "m2"}))
    ans = json.loads(dw.receive_text())
    assert ans["type"] == "answer" and ans["mac"] == "m2"
    dws.__exit__(None, None, None)
    aws.__exit__(None, None, None)


def test_revocation_blocks_and_closes(env):
    c, _ = env
    aid, asec = mk_agent(c)
    aws, aw, r = pair(c, aid, asec)
    aw.receive_text()
    d = r.json()
    dws, dw = ws_auth(c, "device", d["device_id"], d["device_token"])
    dw.receive_text(); dw.receive_text()
    assert c.delete(f"/api/devices/{d['device_id']}", headers=hdr(aid, asec)).status_code == 200
    assert json.loads(aw.receive_text())["type"] == "device_revoked"
    assert c.get("/api/status", headers=hdr(d["device_id"], d["device_token"])).status_code == 401
    # other agent cannot revoke
    aid2, asec2 = mk_agent(c)
    assert c.delete(f"/api/devices/{d['device_id']}", headers=hdr(aid2, asec2)).status_code == 404
    aws.__exit__(None, None, None)


def test_offline_agent_notice(env):
    c, _ = env
    aid, asec = mk_agent(c)
    aws, aw, r = pair(c, aid, asec)
    aw.receive_text()
    d = r.json()
    aws.__exit__(None, None, None)
    dws, dw = ws_auth(c, "device", d["device_id"], d["device_token"])
    dw.receive_text()
    assert json.loads(dw.receive_text())["online"] is False
    dw.send_text(json.dumps({"type": "offer", "session_id": "s", "sdp": "x"}))
    assert json.loads(dw.receive_text())["type"] == "agent_offline"
    dws.__exit__(None, None, None)


def test_register_key_enforced():
    c = TestClient(create_app(":memory:", register_key="k"))
    assert c.post("/api/agents/register", json={"name": "x"}).status_code == 403
    assert c.post("/api/agents/register", json={"name": "x"}, headers={"X-Register-Key": "k"}).status_code == 200


def test_secrets_stored_hashed(env):
    c, app = env
    aid, asec = mk_agent(c)
    row = app.state.db._q("SELECT secret_hash FROM agents WHERE id=?", (aid,), one=True)
    assert asec not in row["secret_hash"] and len(row["secret_hash"]) == 64
