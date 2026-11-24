import json
import socket
import urllib.error
import urllib.request

import pytest

from tests.conftest import wait_status


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def call(port, path, key=None, body=None, method=None, raw=None, headers=None):
    h = dict(headers or {})
    if key:
        h["Authorization"] = f"Bearer {key}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


@pytest.fixture
def api(ctx):
    port = free_port()
    ctx.sm.update({"api": {"enabled": True, "port": port}})
    assert ctx.local_api.running and ctx.local_api.port == port
    return ctx, port


def test_disabled_by_default_and_binds_loopback_only(ctx):
    assert not ctx.local_api.running
    port = free_port()
    ctx.sm.update({"api": {"enabled": True, "port": port}})
    assert ctx.local_api._srv.server_address[0] == "127.0.0.1"
    ctx.sm.update({"api": {"enabled": False}})
    assert not ctx.local_api.running
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_requires_key(api):
    ctx, port = api
    assert call(port, "/api/v1/status")[0] == 401
    assert call(port, "/api/v1/status", key="wrong")[0] == 401
    assert call(port, "/api/v1/links", key="wrong", body={"urls": ["http://x"]})[0] == 401
    assert any(a["action"] == "api_auth_failed" for a in ctx.repo.list_activity(category="security"))
    code, st = call(port, "/api/v1/status", key=ctx.local_api.key())
    assert code == 200 and "queued" in st
    code, _ = call(port, "/api/v1/status", headers={"X-API-Key": ctx.local_api.key()})
    assert code == 200


def test_links_are_queued_and_published(api, server, fake_bale):
    ctx, port = api
    code, res = call(port, "/api/v1/links", ctx.local_api.key(),
                     {"urls": [server.url("/small.pdf"), "http://not-valid", server.url("/small.pdf")]})
    assert code == 200
    r = res["results"]
    assert r[0]["ok"] and r[0]["job_id"] and not r[1]["ok"] and r[2]["code"] == "duplicate_active"
    wait_status(ctx, r[0]["job_id"], ("completed",))
    assert fake_bale.sent and ctx.repo.get_job(r[0]["job_id"])["source"] == "import"


def test_input_validation_and_limits(api):
    ctx, port = api
    k = ctx.local_api.key()
    assert call(port, "/api/v1/links", k, raw=b"{not json")[0] == 400
    assert call(port, "/api/v1/links", k, body={"urls": "x"})[0] == 400
    assert call(port, "/api/v1/links", k, body={"nourls": 1})[0] == 400
    assert call(port, "/api/v1/links", k, body={"urls": ["http://a"] * 21})[0] == 400
    assert call(port, "/api/v1/links", k, raw=b"x" * (70 * 1024))[0] == 413
    assert call(port, "/api/v1/unknown", k, body={})[0] == 404
    assert call(port, "/api/v1/links", k, body={"urls": ["http://a"], "destinations": ["x"]})[0] == 400


def test_key_is_secret_and_regenerable(api, tmp_path):
    ctx, port = api
    old = ctx.local_api.key()
    assert len(old) >= 40
    from app.core.logger import mask_text
    assert old not in mask_text(f"oops {old}")
    new = ctx.local_api.regenerate_key()
    assert new != old and call(port, "/api/v1/status", old)[0] == 401 and call(port, "/api/v1/status", new)[0] == 200
    for p in ctx.home.rglob("*"):
        if p.is_file() and p.suffix in (".db", ".json", ".log") and "secrets" not in p.name:
            assert new.encode() not in p.read_bytes()
