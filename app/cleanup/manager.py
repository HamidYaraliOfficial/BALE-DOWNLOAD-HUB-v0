"""Guaranteed clean-up of temporary data. Deletes ONLY inside <download_dir>/<job-uuid>/ folders."""
from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from app.core import events
from app.core.constants import TERMINAL_STATUSES

log = logging.getLogger(__name__)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass
class CleanupReport:
    files_removed: int = 0
    bytes_freed: int = 0
    status: str = "ok"          # ok | partial | failed | nothing
    note: str = ""


def _scan(path: Path) -> tuple[int, int]:
    n = b = 0
    for root, _d, files in os.walk(path):
        for f in files:
            n += 1
            try:
                b += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n, b


def _force_remove(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


class CleanupManager:
    def __init__(self, repo, get_settings, bus: events.EventBus | None = None):
        self._repo, self._gs, self._bus = repo, get_settings, bus

    # ---------------------------------------------------------------- paths
    def base_dir(self) -> Path:
        p = Path(self._gs().download.directory)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def job_dir(self, job_id: str) -> Path:
        if not _UUID.match(job_id):
            raise ValueError("invalid job id")
        return self.base_dir() / job_id

    def _inside_base(self, p: Path) -> bool:
        base = self.base_dir().resolve()
        try:
            return p.resolve().parent == base
        except OSError:
            return False

    # ---------------------------------------------------------------- per job
    def cleanup_job(self, job_id: str, reason: str = "published", scrub: bool | None = None) -> CleanupReport:
        """Delete every temp artefact of ONE job: media, processed copies, thumbnails, sidecars, caches."""
        d = self.job_dir(job_id)
        rep = CleanupReport(status="nothing")
        if d.exists() and self._inside_base(d):
            rep.files_removed, rep.bytes_freed = _scan(d)
            for attempt in range(4):                      # Windows: AV / indexer may hold files briefly
                shutil.rmtree(d, onexc=_force_remove)
                if not d.exists():
                    break
                time.sleep(0.2 * (attempt + 1))
            if d.exists():
                left_n, left_b = _scan(d)
                rep.files_removed -= left_n
                rep.bytes_freed -= left_b
                rep.status, rep.note = "partial" if rep.files_removed else "failed", f"{left_n} file(s) could not be removed"
            else:
                rep.status = "ok"
        self._repo.add_cleanup(job_id, reason, rep.files_removed, rep.bytes_freed, rep.status, rep.note)
        self._repo.mark_cleanup(job_id, rep.status if rep.status != "nothing" else "ok")
        job = self._repo.get_job(job_id)
        privacy = self._gs().cleanup.privacy_mode if scrub is None else scrub
        if privacy and job and job["status"] in TERMINAL_STATUSES and rep.status in ("ok", "nothing"):
            self._repo.scrub_job(job_id)
        if self._bus and rep.status != "nothing":
            self._bus.publish(events.CLEANUP_DONE, job_id=job_id, freed=rep.bytes_freed, status=rep.status)
        return rep

    # ---------------------------------------------------------------- global sweeps
    def sweep_orphans(self, include_idle_older_than_h: float | None = None, reason: str = "orphan") -> CleanupReport:
        """Remove job folders whose job no longer exists or is finished. Live jobs are never touched."""
        total = CleanupReport(status="nothing")
        live = self._repo.live_job_ids()
        known = self._repo.all_job_ids()
        cutoff = None if include_idle_older_than_h is None else time.time() - include_idle_older_than_h * 3600
        for child in self.base_dir().iterdir():
            if not child.is_dir() or not _UUID.match(child.name):
                continue                                   # foreign data is never touched
            if child.name in live:
                continue
            orphan = child.name not in known
            if not orphan:
                j = self._repo.get_job(child.name)
                finished = j and j["status"] in TERMINAL_STATUSES
                if not finished and not (cutoff and child.stat().st_mtime < cutoff):
                    continue
            n, b = _scan(child)
            shutil.rmtree(child, onexc=_force_remove)
            ok = not child.exists()
            total.files_removed += n if ok else 0
            total.bytes_freed += b if ok else 0
            total.status = "ok" if ok and total.status in ("nothing", "ok") else "partial"
            self._repo.add_cleanup(child.name if not orphan else None, reason, n, b if ok else 0,
                                   "ok" if ok else "failed")
        if total.status != "nothing" and self._bus:
            self._bus.publish(events.CLEANUP_DONE, job_id=None, freed=total.bytes_freed, status=total.status)
        return total

    def retry_failed(self) -> int:
        n = 0
        for j in self._repo.jobs_needing_cleanup_retry():
            if j["status"] in TERMINAL_STATUSES:
                if self.cleanup_job(j["id"], "retry").status in ("ok", "nothing"):
                    n += 1
        return n

    def usage(self) -> dict:
        """Real numbers for the dashboard: how many temp files / bytes are on disk right now."""
        files = size = 0
        for child in self.base_dir().iterdir():
            if child.is_dir():
                a, b = _scan(child)
                files, size = files + a, size + b
        try:
            free = shutil.disk_usage(self.base_dir()).free
            total = shutil.disk_usage(self.base_dir()).total
        except OSError:
            free = total = 0
        return {"temp_files": files, "temp_bytes": size, "disk_free": free, "disk_total": total}

    def list_orphans(self) -> list[Path]:
        live, known = self._repo.live_job_ids(), self._repo.all_job_ids()
        return [c for c in self.base_dir().iterdir()
                if c.is_dir() and _UUID.match(c.name) and c.name not in live
                and (c.name not in known or (self._repo.get_job(c.name) or {}).get("status") in TERMINAL_STATUSES)]
