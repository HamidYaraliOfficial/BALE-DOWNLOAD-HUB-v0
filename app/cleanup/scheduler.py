"""Background maintenance: orphan sweep, retry failed clean-ups, DB retention, disk watch."""
from __future__ import annotations

import logging
import shutil
import threading

from app.core import events
from app.core.logger import prune_old_logs
from app.core import paths

log = logging.getLogger(__name__)


class CleanupScheduler:
    def __init__(self, cleanup, repo, get_settings, bus, queue_getter=None):
        self._c, self._repo, self._gs, self._bus = cleanup, repo, get_settings, bus
        self._queue = queue_getter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._disk_warned = False

    def start(self) -> None:
        s = self._gs()
        if s.cleanup.cleanup_on_startup:
            self.run_once(startup=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="cleanup-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(max(30, self._gs().cleanup.interval_min * 60))
            if self._stop.is_set():
                break
            try:
                self.run_once()
            except Exception:
                log.exception("scheduled maintenance failed")

    def run_once(self, startup: bool = False) -> dict:
        s = self._gs()
        rep = self._c.sweep_orphans(include_idle_older_than_h=s.cleanup.orphan_max_age_hours,
                                    reason="startup" if startup else "scheduled")
        retried = self._c.retry_failed()
        purged = self._repo.purge_old(
            s.logging.db_retention_days,
            archive_dir=(paths.app_home() / "archive") if s.logging.archive_before_purge else None)
        prune_old_logs(paths.log_dir(), s.logging.retention_days)
        self.check_disk()
        return {"freed": rep.bytes_freed, "files": rep.files_removed, "retried": retried, "purged": purged}

    def check_disk(self) -> bool:
        """Returns True when free space is below the configured minimum (and pauses the queue)."""
        s = self._gs()
        try:
            free = shutil.disk_usage(self._c.base_dir()).free
        except OSError:
            return False
        low = free < s.download.min_free_disk_mb * 1024 * 1024
        if low and not self._disk_warned:
            self._disk_warned = True
            self._bus.publish(events.DISK_LOW, free=free)
            if self._queue and self._queue():
                self._queue().pause_queue(reason="disk_low")
        elif not low:
            self._disk_warned = False
        return low
