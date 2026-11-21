"""SQLite storage. Only hashes of secrets + minimal metadata are stored."""
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time


def hash_secret(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class DB:
    def __init__(self, path: str = ":memory:"):
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._c.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY, name TEXT, secret_hash TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, agent_id TEXT, name TEXT,
                token_hash TEXT, created REAL, revoked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS pair_codes(lookup TEXT PRIMARY KEY, agent_id TEXT, expires REAL);
            """
        )

    def _q(self, sql, args=(), one=False, commit=False):
        with self._lock:
            cur = self._c.execute(sql, args)
            if commit:
                self._c.commit()
            return (cur.fetchone() if one else cur.fetchall()) if not commit else None

    # agents
    def create_agent(self, name: str):
        aid = "a_" + secrets.token_hex(8)
        secret = secrets.token_urlsafe(32)
        self._q("INSERT INTO agents VALUES(?,?,?,?)", (aid, name[:64], hash_secret(secret), time.time()), commit=True)
        return aid, secret

    def auth_agent(self, aid: str, secret: str):
        r = self._q("SELECT * FROM agents WHERE id=?", (aid,), one=True)
        if r and hmac.compare_digest(r["secret_hash"], hash_secret(secret)):
            return dict(r)
        return None

    # pairing
    def add_code(self, agent_id: str, lookup: str, ttl: float) -> bool:
        now = time.time()
        self._q("DELETE FROM pair_codes WHERE expires<?", (now,), commit=True)
        if self._q("SELECT 1 FROM pair_codes WHERE lookup=?", (lookup,), one=True):
            return False
        self._q("DELETE FROM pair_codes WHERE agent_id=?", (agent_id,), commit=True)  # one live code per agent
        self._q("INSERT INTO pair_codes VALUES(?,?,?)", (lookup, agent_id, now + ttl), commit=True)
        return True

    def consume_code(self, lookup: str):
        r = self._q("SELECT * FROM pair_codes WHERE lookup=?", (lookup,), one=True)
        if not r:
            return None
        self._q("DELETE FROM pair_codes WHERE lookup=?", (lookup,), commit=True)
        if r["expires"] < time.time():
            return None
        return dict(r)

    # devices
    def create_device(self, agent_id: str, name: str):
        did = "d_" + secrets.token_hex(8)
        token = secrets.token_urlsafe(32)
        self._q("INSERT INTO devices VALUES(?,?,?,?,?,0)", (did, agent_id, name[:64], hash_secret(token), time.time()), commit=True)
        return did, token

    def auth_device(self, did: str, token: str):
        r = self._q("SELECT * FROM devices WHERE id=? AND revoked=0", (did,), one=True)
        if r and hmac.compare_digest(r["token_hash"], hash_secret(token)):
            return dict(r)
        return None

    def get_device(self, did: str):
        r = self._q("SELECT * FROM devices WHERE id=?", (did,), one=True)
        return dict(r) if r else None

    def list_devices(self, agent_id: str):
        return [dict(r) for r in self._q("SELECT id,name,created FROM devices WHERE agent_id=? AND revoked=0", (agent_id,))]

    def revoke_device(self, did: str):
        self._q("UPDATE devices SET revoked=1 WHERE id=?", (did,), commit=True)

    def get_agent(self, aid: str):
        r = self._q("SELECT id,name FROM agents WHERE id=?", (aid,), one=True)
        return dict(r) if r else None
