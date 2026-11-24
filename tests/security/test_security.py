import ast
import re
import zipfile
from pathlib import Path

import pytest

from app.core.exceptions import NotDownloadable
from app.downloader.validators import safe_join
from app.media.analyzer import inspect_zip
from app.media.processor import MediaProcessor
from app.core.config import DownloadSettings, MediaSettings
from tests.conftest import wait_status
from tests.helpers import TOKEN

APP = Path(__file__).resolve().parents[2] / "app"


def py_files():
    return [p for p in APP.rglob("*.py")]


def test_no_shell_execution_or_dangerous_calls_in_source():
    bad = []
    for f in py_files():
        src = f.read_text(encoding="utf-8")
        if re.search(r"shell\s*=\s*True", src) or re.search(r"\bos\.system\(", src) or re.search(r"\bos\.popen\(", src):
            bad.append(f.name)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                bad.append(f"{f.name}:{node.lineno}")
            if isinstance(node, ast.Import) and any(a.name == "pickle" for a in node.names):
                bad.append(f"{f.name}: pickle")
    assert not bad, bad


def test_subprocess_always_uses_argument_lists():
    for f in py_files():
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "Popen", "call", "check_output") \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                assert isinstance(node.args[0], (ast.List, ast.Name, ast.Tuple)) or node.args[0].__class__.__name__ == "List", f.name


def test_downloaded_files_are_never_executed_or_opened_with_shell():
    src = "\n".join(f.read_text(encoding="utf-8") for f in py_files())
    assert "os.startfile" not in src and "webbrowser" not in src


def test_zip_slip_and_bomb_detection(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../outside.txt", "x")
        zf.writestr("/abs.txt", "x")
        zf.writestr("C:\\win.txt", "x")
        zf.writestr("fine/ok.txt", "x")
    info = inspect_zip(z)
    assert len(info.unsafe_paths) == 3
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.bin", b"\0" * (80 * 1024 * 1024))
    assert inspect_zip(bomb).suspicious_ratio
    mp = MediaProcessor(lambda: DownloadSettings(), lambda: MediaSettings())
    for f in (z, bomb):
        with pytest.raises(NotDownloadable) as e:
            mp.process(str(f), "archive")
        assert e.value.code == "unsafe_archive"


def test_executables_blocked_even_when_allowed_type_is_other(tmp_path):
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"MZ\x90\x00" + b"\0" * 200)
    with pytest.raises(NotDownloadable) as e:
        MediaProcessor(lambda: DownloadSettings(), lambda: MediaSettings()).process(str(exe), "other")
    assert e.value.code == "executable_blocked"
    # the user may explicitly allow them (setting) – then it is not blocked
    MediaProcessor(lambda: DownloadSettings(block_executables=False), lambda: MediaSettings()).process(str(exe), "other")


def test_signature_check_can_be_trusted_over_extension(tmp_path):
    fake = tmp_path / "photo.jpg"
    fake.write_bytes(b"<html><body>login</body></html>")
    with pytest.raises(NotDownloadable) as e:
        MediaProcessor(lambda: DownloadSettings(), lambda: MediaSettings()).process(str(fake), "image")
    assert e.value.code == "html_instead_of_file"


def test_rename_features_cannot_write_outside_directory(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-1.4 test")
    mp = MediaProcessor(lambda: DownloadSettings(), lambda: MediaSettings(name_prefix="../../", name_suffix="/..", rename_pattern=""))
    res = mp.process(str(f), "document")
    assert Path(res.path).parent == tmp_path and ".." not in Path(res.path).name


def test_virus_scan_never_reports_clean_without_engine(tmp_path, monkeypatch):
    from app.security import scanner
    monkeypatch.setattr(scanner, "_defender_path", lambda: None)
    monkeypatch.setattr(scanner.shutil, "which", lambda n: None)
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    assert scanner.scan_file(str(f)).status == "unavailable"


def test_scan_engine_result_mapping(tmp_path, monkeypatch):
    from app.security import scanner
    import subprocess
    f = tmp_path / "a.bin"; f.write_bytes(b"x")
    monkeypatch.setattr(scanner.shutil, "which", lambda n: "/usr/bin/clamscan")
    monkeypatch.setattr(scanner, "_defender_path", lambda: None)
    for code, status in ((0, "clean"), (1, "infected"), (2, "error")):
        monkeypatch.setattr(scanner.subprocess, "run", lambda *a, c=code, **k: subprocess.CompletedProcess(a, c, "FOUND", ""))
        assert scanner.scan_file(str(f)).status == status
    monkeypatch.setattr(scanner.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1)))
    assert scanner.scan_file(str(f)).status == "error"


def test_infected_file_is_rejected_and_cleaned(ctx, server, monkeypatch):
    from app.security import scanner
    monkeypatch.setattr(scanner, "scan_file", lambda p, timeout=300: scanner.ScanResult("infected", "test", "EICAR"))
    import app.media.processor as mp
    monkeypatch.setattr(mp, "scan_file", scanner.scan_file)
    ctx.sm.update({"media": {"scan_with_defender": True}})
    r = ctx.downloads.add_job(server.url("/small.pdf"))
    j = wait_status(ctx, r.job["id"], ("failed",))
    assert j["error_code"] == "malware_detected" and not (ctx.cleanup.base_dir() / j["id"]).exists()


def test_token_absent_from_every_persisted_artifact(ctx, server, fake_bale):
    r = ctx.downloads.add_job(server.url("/small.pdf"))
    wait_status(ctx, r.job["id"], ("completed",))
    ctx.runtime.connect()
    try:
        ctx.runtime.test_token("123:BADBADBADBADBADBADBADBAD")
    except Exception:
        pass
    ctx.backup.backup_database(ctx.home / "b.bdhbak")
    ctx.backup.export_settings(ctx.home / "s.json")
    for p in ctx.home.rglob("*"):
        if p.is_file() and p.name not in ("secrets.enc", "secrets.salt") and p.stat().st_size < 50_000_000:
            data = p.read_bytes()
            assert TOKEN.encode() not in data, p.name
            assert b"ABC-DEF1234ghIkl" not in data, p.name
    assert (ctx.home / "secrets.enc").exists() and TOKEN.encode() not in (ctx.home / "secrets.enc").read_bytes()
    assert ctx.runtime.masked_token().startswith("123456:") and "ABC" not in ctx.runtime.masked_token()


def test_no_hardcoded_secrets_in_project():
    root = Path(__file__).resolve().parents[2]
    pat = re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{30,}\b")
    for f in list(root.rglob("*.py")) + list(root.rglob("*.json")) + list(root.rglob("*.md")):
        if "tests" in f.parts or "venv" in f.parts or f.name == "i18n_check.py":
            continue
        assert not pat.search(f.read_text(encoding="utf-8", errors="ignore")), f


def test_update_check_only_https_public_and_never_installs():
    import httpx
    from app.services.update_service import check_for_updates
    ok = httpx.MockTransport(lambda req: httpx.Response(200, json={"version": "9.0.0", "notes": "n", "security": True, "url": "https://x"}))
    r = check_for_updates("https://updates.example/latest.json", transport=ok, allow_private=True)
    assert r.available and r.security and r.latest == "9.0.0"
    assert check_for_updates("").error == "no_feed"
    assert check_for_updates("http://127.0.0.1/x").error == "UrlBlockedError"
    assert check_for_updates("file:///etc/passwd").error == "UrlBlockedError"
