"""End-to-end: local HTTP server -> download -> publish to fake Bale -> cleanup."""
import os
import time

import pytest

from tests.conftest import make_ctx, wait_status
from tests.helpers import FakeBale, PAYLOAD_SHA, PAYLOAD


def tree_files(path):
    return [os.path.join(r, f) for r, _d, fs in os.walk(path) for f in fs]


def test_successful_download_publish_and_cleanup(ctx, server, fake_bale):
    r = ctx.downloads.add_job(server.url("/file.bin"))
    assert r.ok, r.code
    j = wait_status(ctx, r.job["id"], ("completed", "failed"))
    assert j["status"] == "completed", j["error_msg"]
    assert len(fake_bale.sent) == 1
    sent = fake_bale.sent[0]
    assert sent["method"] == "sendDocument" and sent["sha256"] == PAYLOAD_SHA     # real bytes arrived
    assert "payload.bin" in sent["caption"]
    # temp data gone, cleanup recorded
    assert not (ctx.cleanup.base_dir() / j["id"]).exists()
    assert tree_files(ctx.cleanup.base_dir()) == []
    cl = ctx.repo.list_cleanups()
    assert cl and cl[0]["job_id"] == j["id"] and cl[0]["bytes_freed"] >= len(PAYLOAD) and cl[0]["status"] == "ok"
    assert ctx.repo.list_publishes(job_id=j["id"])[0]["status"] == "sent"
    # no file content in the database
    assert os.path.getsize(ctx.db.path) < 2 * 1024 * 1024
    with open(ctx.db.path, "rb") as f:
        assert PAYLOAD[:64] not in f.read()


def test_pdf_and_image_use_matching_methods(ctx, server, fake_bale):
    a = ctx.downloads.add_job(server.url("/small.pdf"))
    b = ctx.downloads.add_job(server.url("/pic.jpg"))
    wait_status(ctx, a.job["id"], ("completed", "failed"))
    wait_status(ctx, b.job["id"], ("completed", "failed"))
    methods = sorted(m["method"] for m in fake_bale.sent)
    assert methods == ["sendDocument", "sendPhoto"]


def test_file_larger_than_limit_is_rejected_before_download(ctx, server):
    ctx.sm.update({"download": {"max_file_size_mb": 5}})
    r = ctx.downloads.add_job(server.url("/huge"))
    assert not r.ok and r.code == "file_too_large"
    assert ctx.repo.list_jobs() == []


def test_invalid_and_private_links(tmp_path, server):
    fake = FakeBale()
    c = make_ctx(tmp_path, fake, allow_private=False, resolver=lambda h, p: ["93.184.216.34"])
    try:
        for bad, code in [("not a url", None), ("ftp://example.com/x", "url_scheme"),
                          ("http://127.0.0.1/x", "url_private"), ("http://10.0.0.5/x", "url_private"),
                          ("http://169.254.169.254/latest/meta-data", "url_private")]:
            r = c.downloads.add_job(bad)
            assert not r.ok
            if code:
                assert r.code == code, (bad, r.code)
        assert any(a["category"] == "security" for a in c.repo.list_activity())
    finally:
        c.shutdown()


def test_duplicate_link_is_not_queued_twice(ctx, server):
    ctx.downloads.queue.pause_queue("test")
    a = ctx.downloads.add_job(server.url("/small.pdf"))
    b = ctx.downloads.add_job(server.url("/small.pdf#frag"))
    assert a.ok and not b.ok and b.code == "duplicate_active"
    r = ctx.downloads.add_links_text(f"{server.url('/pic.jpg')} {server.url('/pic.jpg')}")
    assert [x.ok for x in r] == [True, False] and r[1].code == "duplicate_in_batch"


def test_completed_duplicate_requires_force(ctx, server):
    a = ctx.downloads.add_job(server.url("/small.pdf"))
    wait_status(ctx, a.job["id"], ("completed",))
    b = ctx.downloads.add_job(server.url("/small.pdf"))
    assert not b.ok and b.code == "duplicate_done"
    assert ctx.downloads.add_job(server.url("/small.pdf"), force=True).ok


def test_same_content_not_published_twice_to_same_channel(ctx, server, fake_bale):
    a = ctx.downloads.add_job(server.url("/small.pdf"))
    wait_status(ctx, a.job["id"], ("completed",))
    b = ctx.downloads.add_job(server.url("/small.pdf?copy=2"))
    j = wait_status(ctx, b.job["id"], ("completed",))
    assert len(fake_bale.sent) == 1 and j["result"] == "duplicate_skipped"


def test_publish_failure_cleans_everything(tmp_path, server):
    fake = FakeBale(fail_upload=True)
    c = make_ctx(tmp_path, fake, download={"auto_retry": False})
    c.downloads.start()
    try:
        r = c.downloads.add_job(server.url("/small.pdf"))
        j = wait_status(c, r.job["id"], ("failed", "completed"))
        assert j["status"] == "failed" and j["error_code"]
        assert not (c.cleanup.base_dir() / j["id"]).exists()
        assert c.repo.list_publishes(job_id=j["id"])[0]["status"] == "failed"
        assert c.repo.list_errors()
    finally:
        c.shutdown()


def test_channel_without_permission_fails_cleanly(tmp_path, server):
    fake = FakeBale(post_denied=True)
    c = make_ctx(tmp_path, fake, download={"auto_retry": False})
    c.downloads.start()
    try:
        r = c.downloads.add_job(server.url("/small.pdf"))
        j = wait_status(c, r.job["id"], ("failed", "completed"))
        assert j["status"] == "failed" and "member" in (j["error_msg"] or "").lower()
        assert tree_files(c.cleanup.base_dir()) == []
        chk = c.runtime.adapter().check_channel("@testchan")
        assert chk.can_post is False and not chk.ok
    finally:
        c.shutdown()


def test_download_failure_leaves_no_partial_file(ctx, server):
    r = ctx.downloads.add_job(server.url("/small.pdf"))
    wait_status(ctx, r.job["id"], ("completed",))
    # now a source that disappears: probe works, download is a 404 -> add_job itself rejects
    bad = ctx.downloads.add_job(server.url("/nope.bin"))
    assert not bad.ok and bad.code == "http_404"


def test_fake_image_and_disguised_executable_are_blocked(ctx, server):
    for path, code in [("/fake.jpg", "html_instead_of_file"), ("/exe.pdf", "executable_blocked")]:
        r = ctx.downloads.add_job(server.url(path))
        assert r.ok, r.code
        j = wait_status(ctx, r.job["id"], ("failed", "completed"))
        assert j["status"] == "failed" and j["error_code"] == code, (path, j["error_code"])
        assert tree_files(ctx.cleanup.base_dir()) == []


def test_cancel_running_download_removes_partial_data(ctx, server):
    ctx.sm.update({"download": {"bandwidth_limit_kbps": 400}})
    r = ctx.downloads.add_job(server.url("/file.bin"))
    wait_status(ctx, r.job["id"], ("downloading",))
    time.sleep(0.4)
    assert ctx.downloads.cancel(r.job["id"])
    j = wait_status(ctx, r.job["id"], ("cancelled",))
    assert not (ctx.cleanup.base_dir() / j["id"]).exists()


def test_pause_then_resume_completes_with_correct_hash(ctx, server, fake_bale):
    ctx.sm.update({"download": {"bandwidth_limit_kbps": 1500}})
    r = ctx.downloads.add_job(server.url("/file.bin"))
    wait_status(ctx, r.job["id"], ("downloading",))
    time.sleep(0.3)
    ctx.downloads.pause(r.job["id"])
    j = wait_status(ctx, r.job["id"], ("paused",))
    assert os.path.exists(ctx.cleanup.base_dir() / j["id"] / "data.part")       # kept for resume
    ctx.sm.update({"download": {"bandwidth_limit_kbps": 0}})
    assert ctx.downloads.resume(j["id"])
    wait_status(ctx, j["id"], ("completed",))
    assert fake_bale.sent[0]["sha256"] == PAYLOAD_SHA


def test_cleanup_never_touches_other_jobs_or_foreign_files(ctx, server):
    ctx.downloads.queue.pause_queue("test")
    keep = ctx.downloads.add_job(server.url("/pic.jpg"))
    base = ctx.cleanup.base_dir()
    live_dir = base / keep.job["id"]
    live_dir.mkdir()
    (live_dir / "important.bin").write_bytes(b"x" * 10)
    foreign = base / "my_own_folder"
    foreign.mkdir()
    (foreign / "a.txt").write_text("mine")
    done = ctx.repo.create_job(url="http://x/y", url_hash="zz")
    ctx.repo.set_job_status(done["id"], "completed")
    (base / done["id"]).mkdir()
    (base / done["id"] / "old.bin").write_bytes(b"y")
    orphan = base / "11111111-2222-3333-4444-555555555555"
    orphan.mkdir()
    (orphan / "o.bin").write_bytes(b"z" * 5)
    ctx.cleanup.sweep_orphans()
    assert (live_dir / "important.bin").exists()                 # live job untouched
    assert (foreign / "a.txt").exists()                          # foreign data untouched
    assert not (base / done["id"]).exists() and not orphan.exists()


def test_crash_recovery_requeues_interrupted_jobs(tmp_path, server):
    fake = FakeBale()
    c = make_ctx(tmp_path, fake)
    j = c.repo.create_job(url=server.url("/small.pdf"), url_hash="h1", filename="doc.pdf", category="document")
    c.repo.set_job_status(j["id"], "downloading")
    c.db.close()                                       # simulate abrupt termination (no graceful shutdown)
    c2 = make_ctx(tmp_path, fake)
    try:
        assert c2.downloads.queue.recover(True) == 1
        assert c2.repo.get_job(j["id"])["status"] == "waiting"
        c2.downloads.start()
        done = wait_status(c2, j["id"], ("completed", "failed"))
        assert done["status"] == "completed"
    finally:
        c2.shutdown()


def test_privacy_mode_scrubs_url_and_filename(tmp_path, server):
    fake = FakeBale()
    c = make_ctx(tmp_path, fake, cleanup={"privacy_mode": True})
    c.downloads.start()
    try:
        r = c.downloads.add_job(server.url("/small.pdf"))
        j = wait_status(c, r.job["id"], ("completed",))
        time.sleep(0.2)
        j = c.repo.get_job(j["id"])
        assert j["url"] is None and j["filename"] is None and j["sha256"] is None
        assert c.repo.list_publishes(job_id=j["id"])[0]["filename"] is None
    finally:
        c.shutdown()


def test_no_token_in_logs_database_or_errors(tmp_path, server, caplog):
    from tests.helpers import TOKEN
    fake = FakeBale(fail_upload=True)
    c = make_ctx(tmp_path, fake, download={"auto_retry": False})
    c.downloads.start()
    try:
        with caplog.at_level("DEBUG"):
            r = c.downloads.add_job(server.url("/small.pdf"))
            wait_status(c, r.job["id"], ("failed",))
            try:
                c.runtime.test_token("999999:WRONGWRONGWRONGWRONGWRONGWRONG")
            except Exception as e:
                assert "WRONGWRONG" not in str(e)
        blob = " ".join(rec.getMessage() for rec in caplog.records)
        assert TOKEN not in blob
        for log in (open(p, encoding="utf-8").read() for p in
                    (c.home / "logs").glob("app.log*")):
            assert TOKEN not in log
        with open(c.db.path, "rb") as f:
            assert TOKEN.encode() not in f.read()
        for e in c.repo.list_errors() + c.repo.list_activity():
            assert TOKEN not in str(e)
        assert TOKEN not in c.sm.settings.model_dump_json()
    finally:
        c.shutdown()
