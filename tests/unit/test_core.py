import logging
import os
import re
from pathlib import Path

import pytest

from app.core.config import AppSettings, SettingsManager
from app.core.exceptions import ConfigError, UrlBlockedError, SecurityError
from app.core.logger import SensitiveFilter, clear_secrets, mask_obj, mask_text, register_secret
from app.database.manager import DatabaseManager
from app.database.models import Base
from app.database.repository import Repository
from app.downloader.validators import (classify, dedupe_links, extract_links, filename_from_headers, safe_join,
                                       sanitize_filename, signature_conflict, sniff, unique_name, read_links_file)
from app.security.access_control import AccessController, RateLimiter, Role
from app.security.secret_store import SecretStore
from app.security.url_safety import normalize_url, validate_url, is_public_ip
from app.services.caption import human_duration, human_size, render_caption
from app.core.exceptions import RateLimited

PUBLIC = lambda h, p: ["93.184.216.34"]


# ---------------------------------------------------------------- masking
def test_mask_text_covers_token_headers_urls():
    s = mask_text("GET https://tapi.bale.ai/bot123456:ABC-DEF1234ghIkl-zyx68W2v1u123ew12/getMe")
    assert "ABC-DEF" not in s and "[BOT_TOKEN]" in s
    assert "secret" not in mask_text("Authorization: Bearer secret")
    assert "hunter2" not in mask_text("password=hunter2")
    assert "abc" not in mask_text("https://x.com/a?token=abc&b=1") and "b=1" in mask_text("https://x.com/a?token=abc&b=1")
    assert "pw" not in mask_text("https://user:pw@host/x")
    assert "sess" not in mask_text("Cookie: session=sess; a=b")


def test_registered_secret_is_masked_even_without_pattern():
    register_secret("my-odd-secret-value")
    try:
        assert "my-odd-secret-value" not in mask_text("oops my-odd-secret-value leaked")
    finally:
        clear_secrets()


def test_mask_obj_masks_sensitive_keys():
    out = mask_obj({"token": "x", "nested": {"Authorization": "y", "ok": "1"}, "list": ["password=abc"]})
    assert out["token"] == "[REDACTED]" and out["nested"]["Authorization"] == "[REDACTED]"
    assert "abc" not in str(out)


def test_logging_filter_masks_exception_text():
    rec = logging.LogRecord("x", logging.ERROR, "f", 1, "failed %s", ("123456:ABC-DEF1234ghIkl-zyx68W2v1u123ew12",), None)
    SensitiveFilter().filter(rec)
    assert "ABC-DEF" not in rec.getMessage()
    try:
        raise RuntimeError("url https://tapi.bale.ai/bot123456:ABC-DEF1234ghIkl-zyx68W2v1u123ew12/x")
    except RuntimeError:
        import sys
        rec = logging.LogRecord("x", logging.ERROR, "f", 1, "boom", (), sys.exc_info())
    SensitiveFilter().filter(rec)
    assert "ABC-DEF" not in (rec.exc_text or "")


# ---------------------------------------------------------------- url safety
@pytest.mark.parametrize("url,code", [
    ("ftp://example.com/x", "url_scheme"), ("file:///etc/passwd", "url_scheme"), ("javascript:alert(1)", "url_scheme"),
    ("http://127.0.0.1/x", "url_private"), ("http://localhost/x", "url_private"), ("http://[::1]/x", "url_private"),
    ("http://10.1.2.3/x", "url_private"), ("http://192.168.1.1/x", "url_private"), ("http://172.16.0.1/x", "url_private"),
    ("http://169.254.169.254/latest/meta-data", "url_private"), ("http://100.64.0.1/x", "url_private"),
    ("http://0.0.0.0/x", "url_private"), ("http://2130706433/x", "url_private"), ("http://0x7f.1/x", "url_private"),
    ("http://[::ffff:127.0.0.1]/x", "url_private"), ("http://printer.local/x", "url_private"),
    ("http://metadata.google.internal/x", "url_private"), ("http://user:pw@example.com/x", "url_credentials"),
    ("", "url_empty"), ("http://exa mple.com", "url_invalid"), ("http:///nohost", "url_invalid"),
])
def test_url_validation_blocks(url, code):
    with pytest.raises(UrlBlockedError) as e:
        validate_url(url, resolver=PUBLIC)
    assert e.value.code == code


def test_dns_resolving_to_private_is_blocked_and_public_allowed():
    with pytest.raises(UrlBlockedError):
        validate_url("http://innocent.example/x", resolver=lambda h, p: ["93.184.216.34", "10.0.0.8"])   # any private IP blocks
    assert validate_url("https://example.com:8443/a", resolver=PUBLIC).port == 8443


def test_is_public_ip():
    assert is_public_ip("8.8.8.8") and not is_public_ip("fe80::1") and not is_public_ip("224.0.0.1") and not is_public_ip("garbage")


def test_normalize_url_for_dedupe():
    assert normalize_url("HTTP://Example.com:80/a#frag") == normalize_url("http://example.com/a")
    assert normalize_url("https://e.com/a?x=1") != normalize_url("https://e.com/a?x=2")


# ---------------------------------------------------------------- validators
def test_extract_and_dedupe_links():
    text = "see https://a.com/x.zip, and (https://b.com/y). also https://a.com/x.zip#top ، http://c.com/z؛"
    links = extract_links(text)
    assert links[0] == "https://a.com/x.zip" and "https://b.com/y" in links and links[-1] == "http://c.com/z"
    uniq, dups = dedupe_links(links)
    assert len(dups) == 1 and len(uniq) == 3


def test_read_links_file_txt_csv(tmp_path):
    (tmp_path / "a.txt").write_text("https://a.com/1\nnoise\nhttps://a.com/2", encoding="utf-8")
    (tmp_path / "b.csv").write_text("name,url\nx,https://b.com/1\ny,https://b.com/2\n", encoding="utf-8")
    assert read_links_file(tmp_path / "a.txt") == ["https://a.com/1", "https://a.com/2"]
    assert read_links_file(tmp_path / "b.csv") == ["https://b.com/1", "https://b.com/2"]
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        read_links_file(big)


@pytest.mark.parametrize("raw", ["../../etc/passwd", "..\\..\\windows\\system32\\cmd.exe", "a/b/c.txt", "CON", "nul.txt",
                                 "bad<>:\"|?*name.pdf", "   ", "....", "x" * 500 + ".mp4", "evil\x00.exe", "trailing. "])
def test_sanitize_filename_is_safe(raw):
    n = sanitize_filename(raw)
    assert n and "/" not in n and "\\" not in n and "\x00" not in n and ".." not in n.split(".")[0:1]
    assert len(n) <= 140 and n.upper().split(".")[0] not in ("CON", "NUL")
    assert not n.endswith((" ", "."))


def test_safe_join_blocks_traversal(tmp_path):
    assert safe_join(tmp_path, "ok.txt").parent == tmp_path.resolve()
    with pytest.raises(SecurityError):
        safe_join(tmp_path, "../escape.txt")
    with pytest.raises(SecurityError):
        safe_join(tmp_path, "/etc/passwd")


def test_unique_name_avoids_collisions(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    assert unique_name(tmp_path, "a.txt") == "a (2).txt"
    assert unique_name(tmp_path, "b.txt") == "b.txt"


def test_filename_from_headers():
    assert filename_from_headers('attachment; filename="r.pdf"', "/x/y", None) == "r.pdf"
    assert filename_from_headers("attachment; filename*=UTF-8''%D9%81%D8%A7%DB%8C%D9%84.pdf", "/x", None).endswith(".pdf")
    assert filename_from_headers(None, "/dir/video%20one.mp4", "video/mp4") == "video one.mp4"
    assert filename_from_headers(None, "/noext", "image/png").endswith(".png")
    assert filename_from_headers('attachment; filename="../../x.sh"', "/", None) == "x.sh"


def test_classify_and_sniff(tmp_path):
    assert classify("a.JPG") == "image" and classify("a.mkv") == "video" and classify("a.xyz", "audio/mpeg") == "audio" and classify("a.bin") == "other"
    cases = {b"\xff\xd8\xff\xe0abc": "image", b"%PDF-1.7": "document", b"PK\x03\x04zz": "archive", b"ID3\x03": "audio",
             b"\x00\x00\x00\x18ftypmp42": "video", b"RIFF\x00\x00\x00\x00WEBPVP8 ": "image"}
    for data, cat in cases.items():
        p = tmp_path / "f"
        p.write_bytes(data + b"\0" * 64)
        assert sniff(p)["category"] == cat
    p.write_bytes(b"MZ\x90\x00" + b"\0" * 60)
    assert sniff(p)["is_executable"]
    p.write_bytes(b"<!DOCTYPE html><html>")
    assert sniff(p)["is_html"]
    assert signature_conflict("image", {"is_html": True, "is_executable": False, "category": None}) == "html_instead_of_file"
    assert signature_conflict("document", {"is_html": False, "is_executable": True, "category": "other"}) == "executable_disguised"
    assert signature_conflict("image", {"is_html": False, "is_executable": False, "category": "video"}) == "type_mismatch"


# ---------------------------------------------------------------- caption
def test_caption_engine():
    ctx = {"filename": "a.mp4", "filesize": "3.0 MB", "duration": "", "resolution": "", "source": "x.com"}
    assert render_caption("{filename}\n{duration} | {resolution} | {filesize}\nSrc: {source}", ctx) == "a.mp4\n3.0 MB\nSrc: x.com"
    assert render_caption("{filename} ({resolution})", ctx) == "a.mp4"
    assert render_caption("{unknown_var}\nplain", ctx) == "plain"
    assert len(render_caption("x" * 5000, {})) == 1024
    assert human_size(0) == "" and human_size(1536) == "1.5 KB" and human_duration(3725) == "1:02:05" and human_duration(65) == "1:05"


# ---------------------------------------------------------------- settings
@pytest.fixture
def repo(tmp_path):
    db = DatabaseManager(tmp_path / "t.db")
    db.migrate()
    return Repository(db)


def test_settings_validation_and_persistence(repo):
    sm = SettingsManager(repo)
    sm.update({"download": {"max_file_size_mb": 20, "concurrent_downloads": 3}})
    for bad in ({"download": {"max_file_size_mb": 0}}, {"download": {"concurrent_downloads": 99}}, {"general": {"theme": "pink"}},
                {"general": {"accent": "red"}}, {"bale": {"api_base": "http://insecure"}}, {"bale": {"proxy": "ftp://x"}},
                {"download": {"allowed_types": ["exe"]}}, {"logging": {"level": "LOUD"}}):
        with pytest.raises(ConfigError):
            sm.update(bad)
    assert sm.settings.download.max_file_size_mb == 20          # invalid changes were not saved
    assert SettingsManager(repo).settings.download.concurrent_downloads == 3
    assert sm.settings.publish.delete_after_upload is True
    sm.update({"publish": {"delete_after_upload": False}})
    assert sm.settings.publish.delete_after_upload is True       # cleanup guarantee cannot be switched off


def test_settings_export_has_no_token(repo, tmp_path):
    sm = SettingsManager(repo)
    out = tmp_path / "s.json"
    sm.export_json(out)
    txt = out.read_text()
    assert "token" not in txt.lower().replace("bot_token", "")
    sm.import_json(out)
    (tmp_path / "bad.json").write_text("{not json")
    with pytest.raises(ConfigError):
        sm.import_json(tmp_path / "bad.json")


# ---------------------------------------------------------------- access / limits
def test_rbac_matrix(repo):
    ac = AccessController(repo)
    for uid, role in ((1, "SUPER_ADMIN"), (2, "ADMIN"), (3, "OPERATOR"), (4, "READ_ONLY")):
        repo.add_user(uid, "", role)
    assert ac.get_role(99) is None and ac.get_role(0) == Role.SUPER_ADMIN
    assert ac.is_authorized(4, "view_status") and not ac.is_authorized(4, "submit_link")
    assert ac.is_authorized(3, "submit_link") and not ac.is_authorized(3, "manage_users")
    assert ac.is_authorized(2, "manage_users") and not ac.is_authorized(2, "manage_admins")
    assert ac.is_authorized(1, "backup_restore") and not ac.is_authorized(2, "backup_restore")
    assert ac.can_assign(1, Role.ADMIN) and not ac.can_assign(2, Role.ADMIN) and ac.can_assign(2, Role.OPERATOR)
    repo.update_user(3, blocked=True)
    assert ac.get_role(3) is None


def test_rate_limiter_window():
    t = [0.0]
    rl = RateLimiter(limit=3, window=60, clock=lambda: t[0])
    for _ in range(3):
        rl.check(1)
    with pytest.raises(RateLimited):
        rl.check(1)
    rl.check(2)                       # other users unaffected
    t[0] = 61
    rl.check(1)


# ---------------------------------------------------------------- secrets
def test_secret_store_encrypted_fallback(tmp_path):
    s = SecretStore(tmp_path, use_keyring=False)
    s.set("tok", "123456:SECRETSECRETSECRETSECRET")
    assert s.get("tok") == "123456:SECRETSECRETSECRETSECRET"
    blob = (tmp_path / "secrets.enc").read_bytes()
    assert b"SECRETSECRET" not in blob
    assert SecretStore(tmp_path, use_keyring=False).get("tok") == "123456:SECRETSECRETSECRETSECRET"
    s.delete("tok")
    assert s.get("tok") is None


# ---------------------------------------------------------------- database
def test_migration_matches_models(tmp_path):
    from sqlalchemy import inspect
    db = DatabaseManager(tmp_path / "m.db")
    db.migrate()
    insp = inspect(db.engine)
    for t in Base.metadata.sorted_tables:
        assert {c["name"] for c in insp.get_columns(t.name)} == {c.name for c in t.columns}, t.name
    assert db.current_revision() == "0001"
    ok, probs = db.integrity_check()
    assert ok and not probs
    fks = {fk["referred_table"] for fk in insp.get_foreign_keys("publish_history")}
    assert fks == {"download_jobs", "channels"}


def test_expected_tables_exist(tmp_path):
    from sqlalchemy import inspect
    db = DatabaseManager(tmp_path / "m.db")
    db.migrate()
    names = set(inspect(db.engine).get_table_names())
    assert {"settings", "bot_accounts", "channels", "authorized_users", "download_jobs", "download_queue", "publish_history",
            "activity_logs", "error_logs", "caption_templates", "cleanup_history", "application_preferences"} <= names
    # no BLOB columns anywhere: file content can never live in the database
    from sqlalchemy import LargeBinary
    for t in Base.metadata.sorted_tables:
        assert not any(isinstance(c.type, LargeBinary) for c in t.columns)


def test_repository_stats_retention_and_queue_order(repo):
    a = repo.create_job(url="u1", url_hash="h1", priority=0)
    b = repo.create_job(url="u2", url_hash="h2", priority=5)
    from datetime import datetime
    order = [j["id"] for j in repo.queue_snapshot()]
    assert order == [b["id"], a["id"]]
    assert repo.next_runnable(datetime.utcnow(), {"h2"})[0]["id"] == a["id"]
    repo.set_job_status(a["id"], "completed", size_done=100)
    assert repo.stats()["completed"] == 1
    repo.add_activity("x", "token=123456:ABC-DEF1234ghIkl-zyx68W2v1u123ew12")
    assert "ABC-DEF" not in repo.list_activity()[0]["detail"]
    counts = repo.purge_old(0)
    assert counts["jobs"] >= 1
    repo.add_channel("@a"); repo.add_channel("@b")
    assert [c["is_default"] for c in repo.list_channels()] == [True, False]
