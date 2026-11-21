from fastapi.testclient import TestClient
from pocketdesk_signaling.app import create_app


def test_web_client_served():
    c = TestClient(create_app(":memory:"))
    r = c.get("/")
    assert r.status_code == 200 and "PocketDesk" in r.text and r.headers["cache-control"] == "no-store"
    r = c.get("/app.js")
    assert r.status_code == 200 and "pd1|offer|" in r.text and "pd1|answer|" in r.text
    for p in ("/config.js", "/sw.js", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"):
        assert c.get(p).status_code == 200, p
    assert c.get("/../app.py").status_code in (404, 405)
