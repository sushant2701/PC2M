from fastapi.testclient import TestClient
from pocketdesk_signaling.app import create_app


def test_web_client_served():
    c = TestClient(create_app(":memory:"))
    r = c.get("/")
    assert r.status_code == 200 and "PocketDesk" in r.text and r.headers["cache-control"] == "no-store"
    r = c.get("/app.js")
    assert r.status_code == 200 and "pd1|offer|" in r.text and "pd1|answer|" in r.text
