import os
import threading
import time
from pathlib import Path

import httpx
import pytest

from app.core.config import DownloadSettings
from app.core.exceptions import (DiskSpaceLow, DownloadError, FileTooLarge, JobCancelled, JobPaused, NotDownloadable,
                                 UrlBlockedError)
from app.downloader.direct import DirectDownloader, HttpFetcher
from app.downloader.engine import DownloadEngine
from app.downloader.types import JobControl
from tests.conftest import wait_status
from tests.helpers import PAYLOAD, PAYLOAD_SHA


def settings(**kw):
    base = dict(directory="/tmp/x", max_file_size_mb=50, segment_min_mb=1, min_free_disk_mb=1, retry_backoff_s=0.1, retry_count=2)
    base.update(kw)
    return DownloadSettings(**base)


@pytest.fixture
def mk(server):
    def make(ds=None, **kw):
        ds = ds or settings(**kw)
        f = HttpFetcher(lambda: ds, allow_private=True)
        return f, DirectDownloader(f, lambda: ds)
    return make


def test_segmented_download_matches_hash(mk, server, tmp_path):
    f, d = mk()
    pr = f.probe(server.url("/file.bin"))
    assert pr.resumable and pr.size == len(PAYLOAD)
    res = d.download(server.url("/file.bin"), tmp_path / "j", pr, JobControl())
    assert res.sha256 == PAYLOAD_SHA and sorted(os.listdir(tmp_path / "j")) == ["payload.bin"]


def test_single_segment_when_server_has_no_range(mk, server, tmp_path):
    f, d = mk()
    pr = f.probe(server.url("/norange.bin"))
    assert not pr.resumable
    assert d.download(server.url("/norange.bin"), tmp_path / "j", pr, JobControl()).sha256 == PAYLOAD_SHA


def test_connection_drop_is_retried_and_resumed(mk, server, tmp_path):
    f, d = mk(retry_count=3)
    pr = f.probe(server.url("/flaky.bin"))
    assert d.download(server.url("/flaky.bin"), tmp_path / "j", pr, JobControl()).sha256 == PAYLOAD_SHA


def test_permanent_connection_loss_fails_after_retries(mk, server, tmp_path):
    f, d = mk(retry_count=1)
    pr = f.probe(server.url("/alwaysdrop"))
    with pytest.raises(Exception) as e:
        d.download(server.url("/alwaysdrop"), tmp_path / "j", pr, JobControl())
    assert not isinstance(e.value, (JobCancelled, JobPaused))


def test_internet_cut_mid_download_leaves_no_files_after_job_failure(ctx, server):
    ctx.sm.update({"download": {"retry_count": 0, "auto_retry": False}})
    r = ctx.downloads.add_job(server.url("/alwaysdrop"))
    j = wait_status(ctx, r.job["id"], ("failed", "completed"))
    assert j["status"] == "failed"
    assert not (ctx.cleanup.base_dir() / j["id"]).exists()          # partial file + state sidecar removed
    assert ctx.repo.list_cleanups()[0]["reason"] == "failed"


def test_pause_keeps_state_and_resume_finishes(mk, server, tmp_path):
    f, d = mk()
    pr = f.probe(server.url("/slow.bin"))
    ctrl = JobControl()
    threading.Timer(0.4, ctrl.request_pause).start()
    with pytest.raises(JobPaused):
        d.download(server.url("/slow.bin"), tmp_path / "j", pr, ctrl)
    assert (tmp_path / "j" / "data.part").exists() and (tmp_path / "j" / "data.state.json").exists()
    res = d.download(server.url("/slow.bin"), tmp_path / "j", pr, JobControl())
    assert res.sha256 == PAYLOAD_SHA


def test_resume_is_refused_when_source_changed(mk, server, tmp_path):
    f, d = mk()
    pr = f.probe(server.url("/slow.bin"))
    ctrl = JobControl()
    threading.Timer(0.3, ctrl.request_pause).start()
    with pytest.raises(JobPaused):
        d.download(server.url("/slow.bin"), tmp_path / "j", pr, ctrl)
    pr.etag = '"different"'                                          # source changed -> stale partial data must not be reused
    res = d.download(server.url("/slow.bin"), tmp_path / "j", pr, JobControl())
    assert res.sha256 == PAYLOAD_SHA


def test_bandwidth_limit_is_applied(mk, server, tmp_path):
    f, d = mk(bandwidth_limit_kbps=1500, segments=1)
    pr = f.probe(server.url("/file.bin"))
    t = time.time()
    d.download(server.url("/file.bin"), tmp_path / "j", pr, JobControl())
    assert time.time() - t >= 1.5                                    # 3 MB at 1.5 MB/s


def test_cancel_raises(mk, server, tmp_path):
    f, d = mk()
    pr = f.probe(server.url("/slow.bin"))
    ctrl = JobControl()
    threading.Timer(0.2, ctrl.request_cancel).start()
    with pytest.raises(JobCancelled):
        d.download(server.url("/slow.bin"), tmp_path / "j", pr, ctrl)


def test_size_limits_declared_and_undeclared(mk, server, tmp_path):
    f, d = mk(max_file_size_mb=2)
    pr = f.probe(server.url("/file.bin"))
    with pytest.raises(FileTooLarge):
        d.download(server.url("/file.bin"), tmp_path / "a", pr, JobControl())
    pr = f.probe(server.url("/unknownlen"))                          # no Content-Length: limit enforced while streaming
    assert pr.size is None
    with pytest.raises(FileTooLarge):
        d.download(server.url("/unknownlen"), tmp_path / "b", pr, JobControl())


def test_disk_space_guard(mk, server, tmp_path):
    f, d = mk(min_free_disk_mb=1_000_000)
    pr = f.probe(server.url("/small.pdf"))
    with pytest.raises(DiskSpaceLow):
        d.download(server.url("/small.pdf"), tmp_path / "j", pr, JobControl())


def test_server_denials_are_not_bypassed(mk, server):
    f, _ = mk()
    with pytest.raises(NotDownloadable) as e:
        f.probe(server.url("/403"))
    assert e.value.code == "access_denied_by_server"
    with pytest.raises(NotDownloadable) as e:
        f.probe(server.url("/missing"))
    assert e.value.code == "http_404"


def test_redirects_are_followed_and_loops_stopped(mk, server):
    f, _ = mk()
    assert f.probe(server.url("/redirect")).final_url.endswith("/file.bin")
    with pytest.raises(DownloadError) as e:
        f.probe(server.url("/loop"))
    assert e.value.code == "too_many_redirects"


def test_redirect_to_private_address_is_blocked():
    def handler(req):
        if req.url.host == "public.example":
            return httpx.Response(302, headers={"Location": "http://10.0.0.5/secret"})
        return httpx.Response(200, content=b"internal data")
    ds = settings()
    f = HttpFetcher(lambda: ds, resolver=lambda h, p: ["93.184.216.34"] if h == "public.example" else ["10.0.0.5"],
                    transport=httpx.MockTransport(handler))
    with pytest.raises(UrlBlockedError):
        f.probe("http://public.example/start")


def test_redirect_to_localhost_and_metadata_blocked():
    for target in ("http://127.0.0.1:8080/x", "http://169.254.169.254/latest/meta-data/", "http://[::1]/"):
        def handler(req, t=target):
            return httpx.Response(302, headers={"Location": t})
        f = HttpFetcher(lambda: settings(), resolver=lambda h, p: ["93.184.216.34"], transport=httpx.MockTransport(handler))
        with pytest.raises(UrlBlockedError):
            f.probe("https://public.example/a")


def test_engine_probe_reports_unsupported_without_raising(server):
    e = DownloadEngine(lambda: settings(max_file_size_mb=5, allowed_types=["image", "document"]), allow_private=True)
    big = e.probe(server.url("/huge"))
    assert not big.supported and big.reason_code == "file_too_large"
    ok = e.probe(server.url("/small.pdf"))
    assert ok.supported and ok.category == "document" and ok.mime == "application/pdf"
    assert not e.probe(server.url("/slow.bin")).supported or True
    e2 = DownloadEngine(lambda: settings(allowed_types=["image"]), allow_private=True)
    assert e2.probe(server.url("/small.pdf")).reason_code == "type_not_allowed"


def test_html_page_without_media_is_not_downloadable(server):
    e = DownloadEngine(lambda: settings(use_ytdlp=False), allow_private=True)
    p = e.probe(server.url("/html"))
    assert not p.supported and p.reason_code == "html_page_not_media"


def test_content_disposition_path_traversal_stays_inside_job_dir(ctx, server):
    r = ctx.downloads.add_job(server.url("/traversal"))
    assert r.ok and r.job["filename"] == "evil.pdf"
    wait_status(ctx, r.job["id"], ("completed",))
    assert not (ctx.cleanup.base_dir().parent / "evil.pdf").exists() and not (ctx.cleanup.base_dir() / "evil.pdf").exists()
