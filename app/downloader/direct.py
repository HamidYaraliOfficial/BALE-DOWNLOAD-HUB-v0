"""HTTP(S) downloader: SSRF-safe redirects, Range/resume, optional multi-connection segments,
bandwidth limiting, size caps and integrity bookkeeping. Never spawns a shell, never executes data."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from collections import deque
from contextlib import closing
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import DownloadSettings
from app.core.exceptions import (DiskSpaceLow, DownloadError, FileTooLarge, JobCancelled, JobPaused,
                                 NotDownloadable, UrlBlockedError)
from app.downloader.retries import RetryableHttp, RetryPolicy, run_with_retries
from app.downloader.types import DownloadResult, JobControl, ProbeInfo, ProgressCb
from app.downloader.validators import (classify, filename_from_headers, safe_join, sanitize_filename,
                                       unique_name)
from app.security.url_safety import Resolver, validate_url

log = logging.getLogger(__name__)
UA = "Mozilla/5.0 (compatible; BaleDownloadHub/1.0)"
REDIRECT_CODES = (301, 302, 303, 307, 308)
MB = 1024 * 1024
PART_NAME, STATE_NAME = "data.part", "data.state.json"


class _SegmentAborted(Exception):
    """Internal: another segment failed, so this one stops. Never surfaced as the job's error."""


class HttpFetcher:
    """httpx wrapper that validates the destination of EVERY redirect hop."""

    def __init__(self, get_settings: Callable[[], DownloadSettings], resolver: Resolver | None = None,
                 transport: httpx.BaseTransport | None = None, allow_private: bool = False,
                 proxy: str | None = None):
        self._gs, self._resolver, self._allow_private = get_settings, resolver, allow_private
        kw = {}
        if transport is not None:
            kw["transport"] = transport
        if proxy:
            kw["proxy"] = proxy
        self._client = httpx.Client(follow_redirects=False, headers={"User-Agent": UA}, **kw)

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, url: str, headers: dict | None = None) -> tuple[httpx.Response, str]:
        s = self._gs()
        timeout = httpx.Timeout(s.read_timeout_s, connect=s.connect_timeout_s)
        cur = url
        for hop in range(s.max_redirects + 1):
            validate_url(cur, self._resolver, self._allow_private)
            req = self._client.build_request(method, cur, headers=headers, timeout=timeout)
            resp = self._client.send(req, stream=True)
            if resp.status_code in REDIRECT_CODES and resp.headers.get("location"):
                loc = urljoin(cur, resp.headers["location"])
                resp.close()
                if hop >= s.max_redirects:
                    raise DownloadError("too many redirects", code="too_many_redirects")
                cur = loc
                continue
            return resp, cur
        raise DownloadError("too many redirects", code="too_many_redirects")  # pragma: no cover

    def probe(self, url: str) -> ProbeInfo:
        resp, final = self.request("HEAD", url, {"Accept-Encoding": "identity"})
        if resp.status_code >= 400 or resp.status_code == 405:
            resp.close()
            resp, final = self.request("GET", url, {"Accept-Encoding": "identity"})
        try:
            if resp.status_code >= 400:
                code = "access_denied_by_server" if resp.status_code in (401, 403) else f"http_{resp.status_code}"
                raise NotDownloadable(f"server answered HTTP {resp.status_code}", code=code)
            h = resp.headers
            mime = (h.get("content-type") or "").split(";")[0].strip().lower() or None
            size = None
            cl = h.get("content-length", "")
            if cl.isdigit():
                size = int(cl)
            cr = h.get("content-range", "")
            if "/" in cr and cr.rsplit("/", 1)[-1].isdigit():
                size = int(cr.rsplit("/", 1)[-1])
            name = filename_from_headers(h.get("content-disposition"), urlsplit(final).path, mime)
            info = ProbeInfo(url=url, final_url=final, kind="direct", filename=name, size=size, mime=mime,
                             category=classify(name, mime), accept_ranges=h.get("accept-ranges", "").lower() == "bytes",
                             etag=h.get("etag"), last_modified=h.get("last-modified"))
            info.resumable = bool(info.size and info.accept_ranges)
            info._is_html = mime in ("text/html", "application/xhtml+xml")  # type: ignore[attr-defined]
            return info
        finally:
            resp.close()


# ---------------------------------------------------------------------------------------------
class BandwidthLimiter:
    def __init__(self, rate_getter: Callable[[], int]):
        self._rate = rate_getter
        self._tokens = 0.0
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n: int, ctrl: JobControl) -> None:
        rate = self._rate()
        if rate <= 0:
            return
        with self._lock:
            now = time.monotonic()
            self._tokens = min(float(rate), self._tokens + (now - self._last) * rate)
            self._last = now
            self._tokens -= n
            delay = -self._tokens / rate if self._tokens < 0 else 0.0
        if delay > 0:
            ctrl.wait(delay)


class _Counter:
    def __init__(self, done: int, total: int | None, cb: ProgressCb | None):
        self.done, self.total, self._cb = done, total, cb
        self._lock = threading.Lock()
        self._win: deque[tuple[float, int]] = deque([(time.monotonic(), done)])
        self._last_emit = 0.0

    def add(self, n: int) -> None:
        with self._lock:
            self.done += n

    def reset(self) -> None:
        with self._lock:
            self.done = 0
            self._win.clear()

    def speed(self) -> float:
        now = time.monotonic()
        with self._lock:
            self._win.append((now, self.done))
            while len(self._win) > 2 and now - self._win[0][0] > 3.0:
                self._win.popleft()
            t0, d0 = self._win[0]
            return max(0.0, (self.done - d0) / (now - t0)) if now > t0 else 0.0

    def emit(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_emit < 0.25:
            return
        self._last_emit = now
        if self._cb:
            try:
                self._cb(self.done, self.total, self.speed())
            except Exception:
                log.debug("progress callback failed", exc_info=True)


class DirectDownloader:
    def __init__(self, fetcher: HttpFetcher, get_settings: Callable[[], DownloadSettings]):
        self._f, self._gs = fetcher, get_settings

    # ------------------------------------------------------------------
    def download(self, url: str, dest_dir: Path, probe: ProbeInfo, ctrl: JobControl,
                 progress: ProgressCb | None = None) -> DownloadResult:
        s = self._gs()
        dest_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = s.max_file_size_mb * MB
        if probe.size and probe.size > max_bytes:
            raise FileTooLarge(f"{probe.size} bytes exceeds limit of {max_bytes}")
        free = shutil.disk_usage(dest_dir).free
        need = (probe.size or 0) + s.min_free_disk_mb * MB
        if free < need:
            raise DiskSpaceLow(f"free space {free} < required {need}")
        part, state_path = dest_dir / PART_NAME, dest_dir / STATE_NAME
        # setting is KiB/s; read live so the user can change it while downloads run
        limiter = BandwidthLimiter(lambda: self._gs().bandwidth_limit_kbps * 1024)
        policy = RetryPolicy(s.retry_count if s.auto_retry else 0, s.retry_backoff_s)

        for attempt_mode in ("ranged", "plain"):
            use_ranges = probe.resumable and attempt_mode == "ranged"
            segs = self._plan(probe, use_ranges, s, part, state_path, url)
            counter = _Counter(sum(sg[2] - sg[0] for sg in segs) if use_ranges else 0, probe.size, progress)
            try:
                self._run(url, probe, segs, use_ranges, part, state_path, ctrl, counter, limiter, policy, max_bytes, s)
                break
            except DownloadError as e:
                if e.code == "range_unsupported" and attempt_mode == "ranged":
                    log.info("server ignored Range – retrying as single plain stream")
                    self._reset(part, state_path)
                    continue
                raise
        size = os.path.getsize(part)
        if probe.size and size != probe.size:
            raise DownloadError(f"size mismatch: got {size}, expected {probe.size}", code="size_mismatch")
        name = unique_name(dest_dir, sanitize_filename(probe.filename, "download"))
        final = safe_join(dest_dir, name)
        os.replace(part, final)
        state_path.unlink(missing_ok=True)
        counter.done = size
        counter.emit(force=True)
        return DownloadResult(path=str(final), size=size, sha256=file_sha256(final), filename=name, kind="direct")

    # ------------------------------------------------------------------
    @staticmethod
    def _reset(part: Path, state_path: Path) -> None:
        part.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)

    def _plan(self, probe: ProbeInfo, use_ranges: bool, s: DownloadSettings, part: Path, state_path: Path,
              url: str) -> list[list]:
        """Return segments as [start, end|None, pos]. Loads saved state when it still matches the source."""
        size = probe.size
        sig = {"url": url, "size": size, "etag": probe.etag, "lm": probe.last_modified}
        if use_ranges and state_path.exists() and part.exists():
            try:
                st = json.loads(state_path.read_text())
                if st.get("sig") == sig and part.stat().st_size == size:
                    segs = st["segments"]
                    log.info("resuming download at %d/%d bytes", sum(x[2] - x[0] for x in segs), size)
                    return segs
            except (ValueError, KeyError, OSError):
                pass
        self._reset(part, state_path)
        with open(part, "wb") as f:
            if use_ranges and size:
                f.truncate(size)
        if not use_ranges:
            return [[0, None, 0]]
        seg_min = s.segment_min_mb * MB
        n = max(1, min(s.segments, size // seg_min)) if size >= seg_min else 1
        step = -(-size // n)
        segs = []
        for i in range(n):
            a, b = i * step, min(size - 1, (i + 1) * step - 1)
            if a <= b:
                segs.append([a, b, a])
        state_path.write_text(json.dumps({"sig": sig, "segments": segs}))
        return segs

    @staticmethod
    def _save_state(state_path: Path, sig: dict, segs: list[list], lock: threading.Lock) -> None:
        with lock:
            tmp = state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"sig": sig, "segments": segs}))
            os.replace(tmp, state_path)

    def _run(self, url, probe, segs, use_ranges, part, state_path, ctrl, counter, limiter, policy, max_bytes, s):
        sig = {"url": url, "size": probe.size, "etag": probe.etag, "lm": probe.last_modified}
        slock = threading.Lock()
        abort = threading.Event()
        chunk = s.chunk_size_kb * 1024

        def check():
            ctrl.check()
            if abort.is_set():
                raise _SegmentAborted()

        def stream_segment(seg: list) -> None:
            def attempt() -> None:
                check()
                start, end = seg[0], seg[1]
                pos = seg[2]
                headers = {"Accept-Encoding": "identity"}
                if use_ranges:
                    if end is not None and pos > end:
                        return
                    headers["Range"] = f"bytes={pos}-{end}"
                    if probe.etag and not probe.etag.startswith("W/"):
                        headers["If-Range"] = probe.etag
                elif pos > 0:                                  # plain stream cannot resume: start over
                    counter.reset()
                    pos = seg[2] = 0
                    with open(part, "wb"):
                        pass
                resp, _ = self._f.request("GET", url, headers)
                with closing(resp):
                    st = resp.status_code
                    if st in (429, 500, 502, 503, 504):
                        ra = resp.headers.get("retry-after", "")
                        raise RetryableHttp(st, float(ra) if ra.replace(".", "", 1).isdigit() else None)
                    if st >= 400:
                        raise NotDownloadable(f"HTTP {st}", code=f"http_{st}")
                    if use_ranges:
                        if st == 206:
                            cr = resp.headers.get("content-range", "")
                            if not cr.startswith(f"bytes {pos}-"):
                                raise DownloadError("unexpected Content-Range", code="range_unsupported")
                        elif st == 200:
                            raise DownloadError("server ignored Range", code="range_unsupported")
                    elif st != 200 and st != 206:
                        raise NotDownloadable(f"HTTP {st}", code=f"http_{st}")
                    with open(part, "r+b") as fh:
                        fh.seek(pos)
                        for data in resp.iter_raw(chunk):
                            check()
                            if end is not None and pos + len(data) > end + 1:
                                data = data[: end + 1 - pos]
                            limiter.consume(len(data), ctrl)
                            fh.write(data)
                            pos += len(data)
                            seg[2] = pos
                            counter.add(len(data))
                            if counter.done > max_bytes:
                                raise FileTooLarge(f"download exceeded limit of {max_bytes} bytes")
                            if end is not None and pos > end:
                                break
                        fh.flush()
                if use_ranges and seg[2] <= seg[1]:
                    raise ConnectionError("connection closed before segment finished")

            run_with_retries(attempt, policy, ctrl)

        n = len(segs)
        ex = ThreadPoolExecutor(max_workers=n, thread_name_prefix="seg")
        futures = [ex.submit(stream_segment, sg) for sg in segs]
        err: BaseException | None = None
        try:
            pending = set(futures)
            last_save = 0.0
            while pending:
                done, pending = wait(pending, timeout=0.4, return_when=FIRST_COMPLETED)
                for f in done:
                    exc = f.exception()
                    if exc is None or isinstance(exc, _SegmentAborted):
                        continue
                    # a user pause/cancel always wins; otherwise keep the FIRST real error
                    if err is None or (isinstance(exc, (JobCancelled, JobPaused))
                                       and not isinstance(err, (JobCancelled, JobPaused))):
                        err = exc
                    abort.set()
                counter.emit()
                if use_ranges and time.monotonic() - last_save > 1.0:
                    self._save_state(state_path, sig, segs, slock)
                    last_save = time.monotonic()
        finally:
            abort.set()
            ex.shutdown(wait=True)
            if use_ranges:
                self._save_state(state_path, sig, segs, slock)
        if err is not None:
            raise err
        counter.emit(force=True)


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(blk)
    return h.hexdigest()
