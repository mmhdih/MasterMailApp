import json
import urllib.error
import urllib.request

from mastermail.db import Database
from mastermail.jobs import JobManager
from mastermail.server import AppServer
from mastermail.service import Service
from mastermail.settings import Settings


def call(url, method="GET", body=None, token="tok", raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers={"X-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_api_requires_token_and_works(env):
    srv = AppServer(Service(Settings(), Database(), JobManager()), token="tok").start()
    base = f"http://127.0.0.1:{srv.port}"
    try:
        assert call(base + "/api/state", token="wrong")[0] == 401
        status, state = call(base + "/api/state")
        assert status == 200 and state["app"]["name"] == "MasterMail"
        with urllib.request.urlopen(base + "/") as r:
            assert b'id="app"' in r.read()
        status, up = call(base + "/api/upload?name=ids.csv", "POST", raw="seller id,email\n1,a@b.ir\n".encode())
        assert status == 200
        status, info = call(base + "/api/file/inspect", "POST", {"file_id": up["file_id"]})
        assert info["detected"]["id"] == "seller id" and info["detected"]["email"] == "email"
        status, c = call(base + "/api/campaigns", "POST", {})
        status, err = call(base + f"/api/campaigns/{c['id']}/source", "POST", {"mode": "ids", "text": "  "})
        assert status == 400 and "شناسه" in err["error"]
        assert call(base + "/api/download?t=tok&path=/etc/passwd")[0] == 404
    finally:
        srv.stop()
