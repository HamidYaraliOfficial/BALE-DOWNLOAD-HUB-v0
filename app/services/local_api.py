"""Optional local HTTP API for handing links to the app from other programs/scripts.

* Disabled by default. When enabled it listens on 127.0.0.1 ONLY (never on the network).
* Every request needs the API key (Authorization: Bearer <key> or X-API-Key). Compared in constant time.
* Tiny request limits (64 KB body, 20 links) and a request-rate limiter.

POST /api/v1/links   {"urls": ["https://..."], "destinations": [channel_id, ...]?}  -> per-link result
GET  /api/v1/status                                                                   -> queue counters
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets as pysecrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.core.logger import register_secret
from app.core.exceptions import RateLimited
from app.security.access_control import LOCAL_USER_ID, RateLimiter

log = logging.getLogger(__name__)
KEY_NAME = "local_api_key"
MAX_BODY = 64 * 1024
MAX_LINKS = 20


class LocalApi:
    def __init__(self, repo, settings_mgr, downloads, secrets_store):
        self.repo, self.sm, self.dl, self.secrets = repo, settings_mgr, downloads, secrets_store
        self._srv: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._limiter = RateLimiter(limit=60, window=60)

    # ------------------------------------------------------------------ key
    def key(self) -> str:
        k = self.secrets.get(KEY_NAME)
        if not k:
            k = pysecrets.token_urlsafe(32)
            self.secrets.set(KEY_NAME, k)
        register_secret(k)
        return k

    def regenerate_key(self) -> str:
        k = pysecrets.token_urlsafe(32)
        self.secrets.set(KEY_NAME, k)
        register_secret(k)
        self.repo.add_activity("api_key_regenerated", "", LOCAL_USER_ID, "security")
        return k

    # ------------------------------------------------------------------ lifecycle
    @property
    def running(self) -> bool:
        return self._srv is not None

    @property
    def port(self) -> int | None:
        return self._srv.server_address[1] if self._srv else None

    def apply_settings(self) -> None:
        s = self.sm.settings.api
        if s.enabled and (not self.running or self.port != s.port):
            self.stop()
            self.start(s.port)
        elif not s.enabled and self.running:
            self.stop()

    def start(self, port: int) -> None:
        api = self
        self.key()

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # keep keys/URLs out of stderr
                pass

            def _json(self, code: int, obj) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _auth(self) -> bool:
                given = self.headers.get("X-API-Key") or ""
                auth = self.headers.get("Authorization") or ""
                if auth.lower().startswith("bearer "):
                    given = auth[7:].strip()
                ok = hmac.compare_digest(given.encode(), api.key().encode())
                if not ok:
                    api.repo.add_activity("api_auth_failed", f"from {self.client_address[0]}", None, "security")
                return ok

            def _gate(self) -> bool:
                try:
                    api._limiter.check(1)
                except RateLimited:
                    self._json(429, {"error": "rate_limited"})
                    return False
                if not self._auth():
                    self._json(401, {"error": "unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._gate():
                    return
                if self.path.split("?")[0] == "/api/v1/status":
                    st = api.repo.stats()
                    self._json(200, {"active": st["active"], "queued": st["queued"], "completed": st["completed"],
                                     "failed": st["failed"], "queue_paused": api.dl.queue.paused})
                else:
                    self._json(404, {"error": "not_found"})

            def do_POST(self):
                if not self._gate():
                    return
                if self.path.split("?")[0] != "/api/v1/links":
                    return self._json(404, {"error": "not_found"})
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return self._json(400, {"error": "bad_length"})
                if n <= 0 or n > MAX_BODY:
                    return self._json(413 if n > MAX_BODY else 400, {"error": "body_size"})
                try:
                    data = json.loads(self.rfile.read(n))
                    urls = data["urls"]
                    if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
                        raise ValueError
                    dest = data.get("destinations") or None
                    if dest is not None and not all(isinstance(d, int) for d in dest):
                        raise ValueError
                except (ValueError, KeyError, TypeError):
                    return self._json(400, {"error": "invalid_json", "expected": {"urls": ["https://..."]}})
                if len(urls) > MAX_LINKS:
                    return self._json(400, {"error": "too_many_links", "max": MAX_LINKS})
                out = []
                for u in urls:
                    r = api.dl.add_job(u, source="import", requester_id=LOCAL_USER_ID, destinations=dest)
                    out.append({"url": u, "ok": r.ok, "job_id": r.job["id"] if r.ok else None,
                                "code": r.code or None})
                api.repo.add_activity("api_links", f"{len(urls)} link(s)", LOCAL_USER_ID, "user")
                self._json(200, {"results": out})

        self._srv = ThreadingHTTPServer(("127.0.0.1", port), H)      # loopback only – by design not configurable
        self._thread = threading.Thread(target=self._srv.serve_forever, name="local-api", daemon=True)
        self._thread.start()
        log.info("local API listening on 127.0.0.1:%s", self.port)

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None
