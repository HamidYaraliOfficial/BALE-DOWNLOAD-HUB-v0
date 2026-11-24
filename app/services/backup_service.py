"""Backup / restore (optionally password-encrypted) and settings export/import. Tokens are never exported."""
from __future__ import annotations

import base64
import logging
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.exceptions import BackupError
from app.core import paths

log = logging.getLogger(__name__)
MAGIC = b"BDHENC1"
REQUIRED_TABLES = {"settings", "download_jobs", "channels", "authorized_users", "alembic_version"}


def _key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=300_000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


class BackupService:
    def __init__(self, db, repo, settings_mgr, on_restored=None):
        self._db, self._repo, self._sm = db, repo, settings_mgr
        self._on_restored = on_restored

    def backup_database(self, dest: Path, password: str | None = None) -> Path:
        dest = Path(dest)
        with tempfile.TemporaryDirectory() as td:
            tmp = self._db.backup_to(Path(td) / "snap.db")
            ok, msg = self._check_sqlite(tmp)
            if not ok:
                raise BackupError(f"database failed integrity check: {msg}", code="backup_integrity")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if password:
                salt = os.urandom(16)
                dest.write_bytes(MAGIC + salt + Fernet(_key(password, salt)).encrypt(tmp.read_bytes()))
            else:
                dest.write_bytes(tmp.read_bytes())
        self._repo.add_activity("backup_created", f"encrypted={bool(password)}", None, "system")
        return dest

    @staticmethod
    def is_encrypted(path: Path) -> bool:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC

    @staticmethod
    def _check_sqlite(path: Path) -> tuple[bool, str]:
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                res = con.execute("PRAGMA integrity_check").fetchall()
                if res != [("ok",)]:
                    return False, str(res[:3])
                tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
                missing = REQUIRED_TABLES - tables
                if missing:
                    return False, f"missing tables: {sorted(missing)}"
                return True, "ok"
            finally:
                con.close()
        except sqlite3.DatabaseError as e:
            return False, str(e)

    def _open_plain(self, path: Path, password: str | None, workdir: Path) -> Path:
        raw = Path(path).read_bytes()
        out = workdir / "restore.db"
        if raw.startswith(MAGIC):
            if not password:
                raise BackupError("backup is encrypted – password required", code="backup_password_required")
            salt, token = raw[len(MAGIC):len(MAGIC) + 16], raw[len(MAGIC) + 16:]
            try:
                out.write_bytes(Fernet(_key(password, salt)).decrypt(token))
            except InvalidToken:
                raise BackupError("wrong password or corrupted backup", code="backup_bad_password") from None
        else:
            out.write_bytes(raw)
        return out

    def verify_backup(self, path: Path, password: str | None = None) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as td:
            try:
                plain = self._open_plain(path, password, Path(td))
            except BackupError as e:
                return False, e.code
            return self._check_sqlite(plain)

    def restore_database(self, path: Path, password: str | None = None) -> None:
        with tempfile.TemporaryDirectory() as td:
            plain = self._open_plain(path, password, Path(td))
            ok, msg = self._check_sqlite(plain)
            if not ok:
                raise BackupError(f"backup is not valid: {msg}", code="backup_invalid")
            safety = paths.app_home() / "backups"
            safety.mkdir(exist_ok=True)
            self._db.backup_to(safety / f"before_restore_{datetime.now():%Y%m%d_%H%M%S}.db")
            self._db.replace_with(plain)
        self._sm.load()
        self._repo.add_activity("backup_restored", "", None, "system")
        if self._on_restored:
            self._on_restored()

    # settings (never contains the token)
    def export_settings(self, path: Path) -> None:
        self._sm.export_json(path)

    def import_settings(self, path: Path):
        return self._sm.import_json(path)
