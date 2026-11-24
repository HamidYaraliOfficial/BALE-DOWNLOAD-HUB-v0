"""Engine/session management, Alembic migrations, integrity check, backup primitives."""
from __future__ import annotations

import logging
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.paths import package_path

log = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._build_engine()

    def _build_engine(self) -> None:
        self.engine = create_engine(f"sqlite:///{self.path}",
                                    connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        self._Session = sessionmaker(self.engine, expire_on_commit=False)

    # ---- migrations
    def migrate(self) -> None:
        cfg = Config()
        cfg.set_main_option("script_location", str(package_path("database", "migrations")))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{self.path}")
        with self.engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")

    def current_revision(self) -> str | None:
        with self.engine.connect() as c:
            try:
                return c.execute(text("select version_num from alembic_version")).scalar()
            except Exception:
                return None

    # ---- sessions
    @contextmanager
    def session_scope(self):
        s: Session = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ---- health
    def integrity_check(self) -> tuple[bool, list[str]]:
        with self.engine.connect() as c:
            rows = [r[0] for r in c.execute(text("PRAGMA integrity_check")).fetchall()]
            fk = c.execute(text("PRAGMA foreign_key_check")).fetchall()
        problems = [r for r in rows if r != "ok"] + [f"foreign key violation: {tuple(r)}" for r in fk]
        return (not problems, problems)

    def size_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                total += p.stat().st_size
        return total

    def vacuum(self) -> None:
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text("VACUUM"))

    def backup_to(self, dest: Path) -> Path:
        """Consistent online copy via the sqlite3 backup API."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        src = sqlite3.connect(self.path)
        try:
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return dest

    def replace_with(self, new_db: Path) -> None:
        """Swap the live database file for `new_db` (already verified by the caller)."""
        self.engine.dispose()
        for suffix in ("-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                p.unlink()
        shutil.copyfile(new_db, self.path)
        self._build_engine()
        self.migrate()

    def close(self) -> None:
        self.engine.dispose()
