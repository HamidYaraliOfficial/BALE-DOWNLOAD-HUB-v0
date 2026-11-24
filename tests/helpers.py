"""Test helpers: a local HTTP server with Range support, flaky/slow endpoints and a fake Bale server."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

PAYLOAD = os.urandom(3 * 1024 * 1024 + 123)          # ~3 MB, deterministic per test session
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
SMALL = b"%PDF-1.4\n" + os.urandom(2048)             # small valid-signature "pdf"
JPEG = b"\xff\xd8\xff\xe0" + os.urandom(4096)


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    flaky_state = {"count": 0}

    def log_message(self, *a):  # silence
        pass

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _ranged(self, data: bytes, honour_range=True, ctype="application/octet-stream", name=None, throttle=0.0,
                drop_after=None):
        hdrs = {"Content-Type": ctype, "ETag": '"abc123"', "Accept-Encoding-Test": "1"}
        if honour_range:
            hdrs["Accept-Ranges"] = "bytes"
        if name:
            hdrs["Content-Disposition"] = f'attachment; filename="{name}"'
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d+)-(\d*)", rng or "")
        if self.command == "HEAD" or not (rng and m and honour_range):
            if self.command == "HEAD":
                self.send_response(200)
                for k, v in hdrs.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return
            return self._stream(200, data, hdrs, throttle, drop_after)
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else len(data) - 1
        b = min(b, len(data) - 1)
        hdrs["Content-Range"] = f"bytes {a}-{b}/{len(data)}"
        self._stream(206, data[a:b + 1], hdrs, throttle, drop_after)

    def _stream(self, status, body, hdrs, throttle, drop_after):
        self.send_response(status)
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        step = 32 * 1024
        sent = 0
        try:
            for i in range(0, len(body), step):
                if drop_after is not None and sent >= drop_after:
                    self.wfile.flush()
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)   # really drop the TCP connection
                    except OSError:
                        pass
                    self.close_connection = True
                    return
                self.wfile.write(body[i:i + step])
                sent += min(step, len(body) - i)
                if throttle:
                    time.sleep(throttle)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/file.bin":
            self._ranged(PAYLOAD, name="payload.bin")
        elif p == "/norange.bin":
            self._ranged(PAYLOAD, honour_range=False, name="norange.bin")
        elif p == "/small.pdf":
            self._ranged(SMALL, ctype="application/pdf", name="doc.pdf")
        elif p == "/pic.jpg":
            self._ranged(JPEG, ctype="image/jpeg")
        elif p == "/slow.bin":
            self._ranged(PAYLOAD, throttle=0.02, name="slow.bin")
        elif p == "/flaky.bin":
            _H.flaky_state["count"] += 1
            first = _H.flaky_state["count"] <= 2 and self.command == "GET"
            self._ranged(PAYLOAD, name="flaky.bin", drop_after=300_000 if first else None)
        elif p == "/alwaysdrop":
            self._ranged(PAYLOAD, name="drop.bin", drop_after=200_000)
        elif p == "/traversal":
            self._ranged(SMALL, ctype="application/pdf", name="../../evil.pdf")
        elif p == "/redirect":
            self._send(302, headers={"Location": "/file.bin"})
        elif p == "/loop":
            self._send(302, headers={"Location": "/loop"})
        elif p == "/html":
            self._send(200, b"<!doctype html><html><body>hello</body></html>", {"Content-Type": "text/html"})
        elif p == "/fake.jpg":   # claims image but is HTML
            self._send(200, b"<html><body>login required</body></html>", {"Content-Type": "image/jpeg"})
        elif p == "/exe.pdf":    # claims pdf but is a PE executable
            self._send(200, b"MZ" + os.urandom(2000), {"Content-Type": "application/pdf"})
        elif p == "/huge":
            self.send_response(200)
            self.send_header("Content-Length", str(900 * 1024 * 1024))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
        elif p == "/unknownlen":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            for _ in range(200):
                self.wfile.write(b"x" * 65536)
            self.close_connection = True
        elif p == "/403":
            self._send(403, b"no")
        elif p == "/503":
            self._send(503, b"busy", {"Retry-After": "0"})
        else:
            self._send(404, b"nf")


class LocalServer:
    def __init__(self):
        _H.flaky_state["count"] = 0
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.port = self.httpd.server_address[1]
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"


# --------------------------------------------------------------------------------- fake Bale
TOKEN = "123456:ABC-DEF1234ghIkl-zyx68W2v1u123ew12"


class FakeBale:
    """In-memory fake of the documented Bale endpoints, usable as httpx MockTransport handler."""

    def __init__(self, token=TOKEN, channel_ok=True, fail_upload=False, post_denied=False):
        self.token, self.channel_ok, self.fail_upload, self.post_denied = token, channel_ok, fail_upload, post_denied
        self.sent: list[dict] = []
        self.sent_messages: list[dict] = []
        self.deleted: list[int] = []
        self.updates: list[dict] = []
        self.next_id = 100
        self.calls: list[str] = []
        self.offsets: list = []
        self.webhook_url = ""
        self.reject_methods: set[str] = set()
        self.deny_chats: set = set()
        self.fail_next: list = []          # list of (status, body) returned for the next calls

    def transport(self):
        return httpx.MockTransport(self.handle)

    def queue_message(self, user_id, text, chat_id=None, update_id=None, chat_type="private", username="u"):
        update_id = update_id if update_id is not None else len(self.updates) + 1
        self.updates.append({"update_id": update_id, "message": {
            "message_id": update_id, "date": 1, "text": text,
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester", "username": username},
            "chat": {"id": chat_id or user_id, "type": chat_type}}})

    def _ok(self, result):
        return httpx.Response(200, json={"ok": True, "result": result})

    def _err(self, code, desc):
        return httpx.Response(code, json={"ok": False, "error_code": code, "description": desc})

    def handle(self, req: httpx.Request):
        path = req.url.path
        m = re.match(r"/bot([^/]+)/(\w+)", path)
        if not m:
            return self._err(404, "Not Found")
        tok, method = m.group(1), m.group(2)
        if tok != self.token:
            return self._err(401, "Unauthorized")
        self.calls.append(method)
        if self.fail_next:
            st, body = self.fail_next.pop(0)
            return httpx.Response(st, json=body)
        if method in self.reject_methods:
            return self._err(400, f"Bad Request: {method} rejected")
        ctype = req.headers.get("content-type", "")
        params: dict = {}
        files: dict = {}
        if ctype.startswith("application/json"):
            params = json.loads(req.content or b"{}")
        elif ctype.startswith("multipart/form-data"):
            body = req.read()
            boundary = re.search(r'boundary=("?)([^";]+)\1', ctype).group(2).encode()
            for part in body.split(b"--" + boundary):
                part = part[2:] if part.startswith(b"\r\n") else part
                if not part or part.startswith(b"--") or b"\r\n\r\n" not in part:
                    continue
                head, _, content = part.partition(b"\r\n\r\n")
                if content.endswith(b"\r\n"):
                    content = content[:-2]
                nm = re.search(rb'name="([^"]+)"', head).group(1).decode()
                fn = re.search(rb'filename="([^"]*)"', head)
                if fn:
                    files[nm] = (fn.group(1).decode(), content)
                else:
                    params[nm] = content.decode()
        if method == "getMe":
            return self._ok({"id": 42, "is_bot": True, "first_name": "Hub", "username": "hub_bot"})
        if method == "getChat":
            cid = params.get("chat_id")
            if not self.channel_ok:
                return self._err(400, "Bad Request: chat not found")
            return self._ok({"id": -1001, "type": "channel", "title": "My Channel",
                             "username": str(cid).lstrip("@") if isinstance(cid, str) else ""})
        if method == "getWebhookInfo":
            return self._ok({"url": self.webhook_url})
        if method == "setWebhook":
            self.webhook_url = params.get("url", "")
            return self._ok(True)
        if method == "getUpdates":
            off = params.get("offset")
            self.offsets.append(off)
            ups = [u for u in self.updates if off is None or u["update_id"] >= int(off)]
            return self._ok(ups)
        if method == "sendMessage":
            if self.post_denied:
                return self._err(403, "Forbidden: bot is not a member of the channel chat")
            self.next_id += 1
            self.sent_messages.append({"chat_id": params.get("chat_id"), "text": params.get("text")})
            return self._ok({"message_id": self.next_id, "chat": {"id": params.get("chat_id")}})
        if method == "deleteMessage":
            self.deleted.append(int(params["message_id"]))
            return self._ok(True)
        if method in ("sendDocument", "sendPhoto", "sendVideo", "sendAudio"):
            if params.get("chat_id") in self.deny_chats or str(params.get("chat_id")) in {str(c) for c in self.deny_chats}:
                return self._err(403, "Forbidden: bot is not a member of the channel chat")
            if self.post_denied:
                return self._err(403, "Forbidden: bot is not a member of the channel chat")
            if self.fail_upload:
                return self._err(500, "Internal error")
            field = {"sendDocument": "document", "sendPhoto": "photo", "sendVideo": "video",
                     "sendAudio": "audio"}[method]
            name, content = files.get(field, ("", b""))
            self.next_id += 1
            self.sent.append({"method": method, "chat_id": params.get("chat_id"), "caption": params.get("caption"),
                              "filename": name, "size": len(content),
                              "sha256": hashlib.sha256(content).hexdigest()})
            return self._ok({"message_id": self.next_id})
        return self._err(404, "Method not found")
