"""Low-level HTTPS client for the Bale Bot API (https://docs.bale.ai).

Verified against the official docs: base `https://tapi.bale.ai/bot<token>/METHOD`, JSON responses
`{ok, result | description, error_code, parameters}`, multipart/form-data for uploads.
The token appears in every URL, so *every* error text is masked before it leaves this module.
"""
from __future__ import annotations

import io
import json
import os
import logging
import time
from typing import Any, Callable

import httpx

from app.core.exceptions import BaleApiError, BaleAuthError, BaleNetworkError
from app.core.logger import mask_text, register_secret

log = logging.getLogger(__name__)
ProgressCb = Callable[[int, int], None]


class ProgressReader(io.BufferedReader):
    """File reader that reports upload progress (httpx streams multipart files via read())."""

    def __init__(self, path: str, cb: ProgressCb | None):
        super().__init__(io.FileIO(path, "rb"))
        self._cb = cb
        self._sent = 0
        self._total = os.path.getsize(path)

    def read(self, size: int = -1) -> bytes:  # noqa: D401
        data = super().read(size)
        if data and self._cb:
            self._sent += len(data)
            try:
                self._cb(min(self._sent, self._total), self._total)
            except Exception:
                pass
        return data


class BaleClient:
    def __init__(self, token: str, api_base: str = "https://tapi.bale.ai", connect_timeout: float = 10,
                 read_timeout: float = 30, upload_timeout: float = 900, retries: int = 3,
                 backoff: float = 2.0, proxy: str | None = None, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        if not token:
            raise BaleAuthError("empty token", error_code=401)
        register_secret(token)
        self._token = token
        self._base = api_base.rstrip("/")
        self._retries, self._backoff, self._sleep = retries, backoff, sleep
        self._connect_timeout, self._read_timeout, self._upload_timeout = connect_timeout, read_timeout, upload_timeout
        kwargs: dict[str, Any] = {}
        if proxy:
            kwargs["proxy"] = proxy
        if transport is not None:
            kwargs["transport"] = transport
        self._http = httpx.Client(timeout=httpx.Timeout(read_timeout, connect=connect_timeout), **kwargs)

    # ------------------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def _url(self, method: str) -> str:
        return f"{self._base}/bot{self._token}/{method}"

    def call(self, method: str, params: dict[str, Any] | None = None, files: dict[str, str] | None = None,
             progress: ProgressCb | None = None, timeout: float | None = None) -> Any:
        """POST a method. `files` maps field name -> local path (sent as multipart)."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        attempt = 0
        while True:
            readers: list[ProgressReader] = []
            try:
                try:
                    if files:
                        mp = {}
                        for field, path in files.items():
                            rd = ProgressReader(path, progress)
                            readers.append(rd)
                            mp[field] = (os.path.basename(path), rd)
                        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                                for k, v in params.items()}
                        resp = self._http.post(self._url(method), data=data, files=mp,
                                               timeout=httpx.Timeout(self._upload_timeout,
                                                                     connect=self._connect_timeout))
                    else:
                        body = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}
                        resp = self._http.post(self._url(method), json=body,
                                               timeout=httpx.Timeout(timeout or self._read_timeout,
                                                                     connect=self._connect_timeout))
                finally:
                    for rd in readers:
                        rd.close()
                return self._parse(resp)
            except httpx.TransportError as e:
                # Uploads are only retried when the request cannot have reached the server.
                safe_to_retry = (not files) or isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout))
                if attempt < self._retries and safe_to_retry:
                    attempt += 1
                    self._sleep(self._backoff * (2 ** (attempt - 1)))
                    continue
                raise BaleNetworkError(mask_text(f"{type(e).__name__}: {e}")) from None
            except BaleApiError as e:
                retryable = e.error_code == 429 or (e.error_code or 0) >= 500
                if retryable and attempt < self._retries and not files:
                    attempt += 1
                    self._sleep(e.retry_after or self._backoff * (2 ** (attempt - 1)))
                    continue
                raise

    def _parse(self, resp: httpx.Response) -> Any:
        try:
            payload = resp.json()
        except ValueError:
            raise BaleApiError(mask_text(f"non-JSON response (HTTP {resp.status_code})"),
                               error_code=resp.status_code) from None
        if payload.get("ok"):
            return payload.get("result")
        code = payload.get("error_code") or resp.status_code
        desc = mask_text(payload.get("description") or f"HTTP {resp.status_code}")
        params = payload.get("parameters") or {}
        retry_after = params.get("retry_after")
        if code in (401, 403) and ("token" in desc.lower() or "unauthor" in desc.lower() or code == 401):
            raise BaleAuthError(desc, error_code=code)
        if code == 404 and "bot" in desc.lower() and "not found" in desc.lower():
            raise BaleAuthError(desc, error_code=code)
        raise BaleApiError(desc, error_code=code, retry_after=retry_after)
