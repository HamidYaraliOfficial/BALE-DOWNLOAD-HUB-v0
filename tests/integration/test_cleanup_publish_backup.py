import json
import os
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest

from app.core.exceptions import BackupError
from app.services.publishing_service import split_file
from app.services.report_service import export_csv, export_json, to_html
from tests.conftest import make_ctx, wait_status
from tests.helpers import FakeBale, TOKEN


def mkjob(ctx, status="completed"):
    j = ctx.repo.create_job(url="http://x/y", url_hash=os.urandom(4).hex())
    ctx.repo.set_job_status(j["id"], status)
    d = ctx.cleanup.job_dir(j["id"])
    d.mkdir(parents=True)
    (d / "a.bin").write_bytes(b"x" * 1000)
    (d / ".thumbs").mkdir()
    (d / ".thumbs" / "t.jpg").write_bytes(b"y" * 10)
    (d / "data.state.json").write_text("{}")
    return j, d


def test_cleanup_removes_everything_and_reports(ctx):
    j, d = mkjob(ctx)
    rep = ctx.cleanup.cleanup_job(j["id"], "published")
    assert rep.status == "ok" and rep.files_removed == 3 and rep.bytes_freed == 1012 and not d.exists()
    h = ctx.repo.list_cleanups()[0]
    assert h["job_id"] == j["id"] and h["bytes_freed"] == 1012 and ctx.repo.total_bytes_freed() == 1012


def test_locked_files_are_reported_and_retried_later(ctx, monkeypatch):
    j, d = mkjob(ctx)
    real = shutil.rmtree
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)         # simulate files held open by another process
    monkeypatch.setattr(time, "sleep", lambda s: None)
    rep = ctx.cleanup.cleanup_job(j["id"], "published")
    assert rep.status == "failed" and d.exists() and ctx.repo.get_job(j["id"])["cleanup_status"] == "failed"
    monkeypatch.setattr(shutil, "rmtree", real)
    assert ctx.cleanup.retry_failed() == 1 and not d.exists()
    assert ctx.repo.get_job(j["id"])["cleanup_status"] == "ok"


def test_invalid_job_id_cannot_escape(ctx):
    for bad in ("../..", "..", "a/b", ""):
        with pytest.raises(ValueError):
            ctx.cleanup.job_dir(bad)


def test_scheduler_sweeps_orphans_and_purges(ctx):
    orphan = ctx.cleanup.base_dir() / "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    orphan.mkdir()
    (orphan / "x").write_bytes(b"1" * 50)
    res = ctx.scheduler.run_once()
    assert res["freed"] == 50 and not orphan.exists()
    assert ctx.cleanup.usage()["temp_files"] == 0


def test_idle_old_job_folder_of_unfinished_job_is_swept_but_live_job_is_not(ctx):
    live, ld = mkjob(ctx, "downloading")
    stale, sd = mkjob(ctx, "paused")
    ctx.repo.set_job_status(stale["id"], "paused")
    old = time.time() - 48 * 3600
    os.utime(sd, (old, old))
    ctx.repo.update_job(stale["id"], status="failed")
    ctx.cleanup.sweep_orphans(include_idle_older_than_h=6)
    assert ld.exists() and not sd.exists()


def test_disk_low_pauses_queue_and_notifies(ctx):
    seen = []
    ctx.bus.subscribe("*", lambda n, **k: seen.append(n))
    ctx.sm.update({"download": {"min_free_disk_mb": 1_000_000}})
    assert ctx.scheduler.check_disk() is True
    assert ctx.downloads.queue.paused and ctx.downloads.queue.pause_reason == "disk_low" and "notify.disk_low" in seen


def test_job_waits_instead_of_failing_when_disk_is_full(ctx, server):
    ctx.sm.update({"download": {"min_free_disk_mb": 1_000_000}})
    r = ctx.downloads.add_job(server.url("/small.pdf"))
    wait_status(ctx, r.job["id"], ("waiting",), 10)
    time.sleep(0.5)
    assert ctx.downloads.queue.paused and ctx.repo.get_job(r.job["id"])["status"] == "waiting"


# ---------------------------------------------------------------- publishing
def test_multi_channel_results_are_reported_per_channel(tmp_path, server):
    fake = FakeBale()
    c = make_ctx(tmp_path, fake, download={"auto_retry": False})
    c.repo.add_channel("@second", "Second")
    c.repo.add_channel("@third", "Third")
    fake.deny_chats = {"@second"}
    c.downloads.start()
    try:
        ids = [x["id"] for x in c.repo.list_channels()]
        r = c.downloads.add_job(server.url("/small.pdf"), destinations=ids)
        j = wait_status(c, r.job["id"], ("failed", "completed"))
        res = {p["channel_label"]: p["status"] for p in c.repo.list_publishes(job_id=j["id"])}
        assert res == {"Test Channel": "sent", "Second": "failed", "Third": "sent"}
        assert j["status"] == "failed"                                   # one channel failed -> job not reported as success
        assert len([m for m in fake.sent]) == 2
        assert tuple(os.listdir(c.cleanup.base_dir())) == ()
    finally:
        c.shutdown()


def test_category_routing(tmp_path, server):
    fake = FakeBale()
    c = make_ctx(tmp_path, fake)
    ch = c.repo.add_channel("@pics", "Pics", categories=["image"])
    c.downloads.start()
    try:
        a = c.downloads.add_job(server.url("/pic.jpg"))
        b = c.downloads.add_job(server.url("/small.pdf"))
        wait_status(c, a.job["id"], ("completed",))
        wait_status(c, b.job["id"], ("completed",))
        by = {m["filename"]: m["chat_id"] for m in fake.sent}
        assert by["pic.jpg"] == "@pics" and by["doc.pdf"] == "@testchan"
    finally:
        c.shutdown()


def test_caption_templates_per_type_and_override(ctx, server, fake_bale):
    ctx.repo.save_template("document", "doc", "DOC: {filename} | {unknown}", True, ctx.repo.get_template_for("document")["id"])
    r = ctx.downloads.add_job(server.url("/small.pdf"))
    wait_status(ctx, r.job["id"], ("completed",))
    assert fake_bale.sent[0]["caption"] == "DOC: doc.pdf"
    r2 = ctx.downloads.add_job(server.url("/pic.jpg"), caption="Custom {filename}")
    wait_status(ctx, r2.job["id"], ("completed",))
    assert fake_bale.sent[1]["caption"] == "Custom pic.jpg"


def test_approval_flow_holds_file_until_approved(ctx, server, fake_bale):
    ctx.sm.update({"publish": {"auto_publish": False}})
    r = ctx.downloads.add_job(server.url("/small.pdf"))
    j = wait_status(ctx, r.job["id"], ("paused",))
    assert j["awaiting_approval"] and fake_bale.sent == []
    assert ctx.downloads.job_file(j) is not None                        # file exists for the preview
    assert ctx.downloads.approve(j["id"])
    wait_status(ctx, j["id"], ("completed",))
    assert len(fake_bale.sent) == 1 and not (ctx.cleanup.base_dir() / j["id"]).exists()


def test_discarding_an_unapproved_job_deletes_its_file(ctx, server):
    ctx.sm.update({"publish": {"auto_publish": False}})
    r = ctx.downloads.add_job(server.url("/small.pdf"))
    j = wait_status(ctx, r.job["id"], ("paused",))
    assert ctx.downloads.cancel(j["id"])
    wait_status(ctx, j["id"], ("cancelled",))
    assert not (ctx.cleanup.base_dir() / j["id"]).exists()


def test_user_quota_enforced_for_bot_users_not_desktop(ctx, server):
    ctx.repo.add_user(77, "Q", "OPERATOR")
    ctx.sm.update({"security": {"user_daily_quota_mb": 1}})
    ctx.downloads.queue.pause_queue("t")
    r = ctx.downloads.add_job(server.url("/file.bin"), "bot", 77)            # 3 MB > 1 MB quota
    assert not r.ok and r.code == "quota_exceeded"
    assert ctx.downloads.add_job(server.url("/file.bin"), "desktop", 0).ok


def test_split_file_parts(tmp_path):
    f = tmp_path / "big.bin"
    f.write_bytes(os.urandom(2500))
    parts = split_file(f, 1000)
    assert [p.name for p in parts] == ["big.bin.001", "big.bin.002", "big.bin.003"]
    assert b"".join(p.read_bytes() for p in parts) == f.read_bytes()


def test_scheduled_job_waits_for_its_time(ctx, server):
    from datetime import datetime, timedelta, timezone
    when = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=2)
    r = ctx.downloads.add_job(server.url("/small.pdf"), scheduled_at=when)
    time.sleep(1.0)
    assert ctx.repo.get_job(r.job["id"])["status"] == "waiting"
    wait_status(ctx, r.job["id"], ("completed",), 15)


def test_queue_priority_order_and_concurrency_limit(ctx, server):
    ctx.sm.update({"download": {"concurrent_downloads": 1, "bandwidth_limit_kbps": 2000}})
    ctx.downloads.queue.pause_queue("t")
    low = ctx.downloads.add_job(server.url("/file.bin"), priority=0).job
    high = ctx.downloads.add_job(server.url("/small.pdf"), priority=5).job
    ctx.downloads.queue.move(low["id"], 1)
    assert ctx.repo.queue_snapshot()[0]["id"] == low["id"]
    ctx.downloads.queue.resume_queue()
    time.sleep(0.5)
    assert ctx.downloads.queue.active_count() <= 1
    wait_status(ctx, low["id"], ("completed",))
    wait_status(ctx, high["id"], ("completed",))


# ---------------------------------------------------------------- backup / reports
def test_backup_roundtrip_plain_and_encrypted(ctx, tmp_path):
    ctx.repo.add_user(1234, "Zed", "ADMIN")
    plain = ctx.backup.backup_database(tmp_path / "p.bdhbak")
    enc = ctx.backup.backup_database(tmp_path / "e.bdhbak", "s3cret")
    assert not ctx.backup.is_encrypted(plain) and ctx.backup.is_encrypted(enc)
    assert TOKEN.encode() not in plain.read_bytes() and b"SQLite format 3" not in enc.read_bytes()
    assert ctx.backup.verify_backup(enc, "s3cret")[0] and not ctx.backup.verify_backup(enc, "wrong")[0]
    ctx.repo.remove_user(1234)
    with pytest.raises(BackupError) as e:
        ctx.backup.restore_database(enc, "bad")
    assert e.value.code == "backup_bad_password" and ctx.repo.get_user(1234) is None       # failed restore changes nothing
    ctx.backup.restore_database(enc, "s3cret")
    assert ctx.repo.get_user(1234)["display_name"] == "Zed"
    assert list((ctx.home / "backups").glob("before_restore_*.db"))                         # safety copy kept


def test_restore_rejects_garbage_and_missing_password(ctx, tmp_path):
    g = tmp_path / "g.bdhbak"
    g.write_bytes(b"this is not a database at all" * 100)
    with pytest.raises(BackupError):
        ctx.backup.restore_database(g)
    enc = ctx.backup.backup_database(tmp_path / "e.bdhbak", "pw")
    with pytest.raises(BackupError) as e:
        ctx.backup.restore_database(enc, None)
    assert e.value.code == "backup_password_required"
    other = tmp_path / "other.db"
    con = sqlite3.connect(other); con.execute("create table x(a)"); con.commit(); con.close()
    assert not ctx.backup.verify_backup(other)[0]


def test_reports_are_masked_and_well_formed(tmp_path):
    rows = [{"ts": "2026-01-01", "detail": f"leak {TOKEN} password=abc", "token": "zzz", "n": 5}]
    c = export_csv(rows, tmp_path / "r.csv")
    j = export_json(rows, tmp_path / "r.json")
    html = to_html("T", rows)
    for blob in (c.read_text(encoding="utf-8-sig"), j.read_text(), html):
        assert TOKEN not in blob and "ABC-DEF" not in blob and "password=abc" not in blob and "zzz" not in blob
    assert json.loads(j.read_text())[0]["n"] == 5


def test_settings_export_import_roundtrip_via_service(ctx, tmp_path):
    ctx.sm.update({"download": {"max_file_size_mb": 33}})
    p = tmp_path / "s.json"
    ctx.backup.export_settings(p)
    assert TOKEN not in p.read_text()
    ctx.sm.update({"download": {"max_file_size_mb": 10}})
    ctx.backup.import_settings(p)
    assert ctx.sm.settings.download.max_file_size_mb == 33


def test_archive_retention_writes_archive_before_delete(ctx, tmp_path):
    ctx.repo.add_activity("old_event", "x")
    from datetime import timedelta
    from app.database import models as m
    with ctx.db.session_scope() as s:
        s.query(m.ActivityLog).update({"ts": m.utcnow() - timedelta(days=200)})
    counts = ctx.repo.purge_old(30, archive_dir=tmp_path / "arch")
    assert counts["activity"] >= 1 and list((tmp_path / "arch").glob("*.jsonl.gz"))
