"""Queue manager: priority dispatch, concurrency limit, pause/resume/cancel, crash recovery."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from app.core import events
from app.core.constants import ACTIVE_STATUSES, JobStatus
from app.downloader.types import JobControl

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class QueueManager:
    def __init__(self, repo, runner: Callable[[dict, JobControl], None], concurrency_getter: Callable[[], int],
                 bus: events.EventBus, on_cancel_waiting: Callable[[str], None] | None = None):
        self._repo, self._runner, self._conc, self._bus = repo, runner, concurrency_getter, bus
        self._on_cancel_waiting = on_cancel_waiting
        self._controls: dict[str, JobControl] = {}
        self._hashes: dict[str, str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._dispatcher: threading.Thread | None = None
        self.paused = False
        self.pause_reason = ""

    # ------------------------------------------------------------ lifecycle
    def recover(self, auto_resume: bool = True) -> int:
        """After a crash/close: jobs left in an active state go back to WAITING (files kept for resume)
        or are failed when auto-resume is off."""
        n = 0
        for j in self._repo.jobs_in_statuses(ACTIVE_STATUSES):
            if j["status"] == JobStatus.CLEANUP.value:
                self._repo.set_job_status(j["id"], JobStatus.FAILED, error_code="interrupted",
                                          cleanup_status="failed")
            elif auto_resume:
                self._repo.set_job_status(j["id"], JobStatus.WAITING)
            else:
                self._repo.set_job_status(j["id"], JobStatus.FAILED, error_code="interrupted")
            n += 1
        return n

    def start(self) -> None:
        if self._dispatcher and self._dispatcher.is_alive():
            return
        self._stop.clear()
        self._dispatcher = threading.Thread(target=self._loop, name="queue-dispatcher", daemon=True)
        self._dispatcher.start()

    def shutdown(self, timeout: float = 8.0) -> None:
        """Pause everything in a resumable way, wait for workers, keep queue state in the DB."""
        self._stop.set()
        with self._lock:
            for c in self._controls.values():
                c.request_pause()
            threads = list(self._threads.values())
        for t in threads:
            t.join(timeout)
        self._wake.set()
        if self._dispatcher:
            self._dispatcher.join(2)

    def wake(self) -> None:
        self._wake.set()

    # ------------------------------------------------------------ dispatch
    def active_count(self) -> int:
        with self._lock:
            return len(self._threads)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.7)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self._dispatch()
            except Exception:
                log.exception("dispatcher error")

    def _dispatch(self) -> None:
        if self.paused:
            return
        with self._lock:
            free = self._conc() - len(self._threads)
            if free <= 0:
                return
            exclude = set(self._hashes.values())
            jobs = self._repo.next_runnable(_now(), exclude, limit=free)
            for job in jobs:
                if job["id"] in self._threads:
                    continue
                ctrl = JobControl()
                self._controls[job["id"]] = ctrl
                if job.get("url_hash"):
                    self._hashes[job["id"]] = job["url_hash"]
                self._repo.set_job_status(job["id"], JobStatus.VALIDATING, attempts=job["attempts"] + 1)
                t = threading.Thread(target=self._work, args=(job, ctrl), name=f"job-{job['id'][:8]}", daemon=True)
                self._threads[job["id"]] = t
                t.start()

    def _work(self, job: dict, ctrl: JobControl) -> None:
        jid = job["id"]
        try:
            self._runner(self._repo.get_job(jid) or job, ctrl)
        except Exception:
            log.exception("job runner crashed for %s", jid)
            cur = self._repo.get_job(jid)
            if cur and cur["status"] in ACTIVE_STATUSES:
                self._repo.set_job_status(jid, JobStatus.FAILED, error_code="internal_error")
        finally:
            with self._lock:
                self._controls.pop(jid, None)
                self._hashes.pop(jid, None)
                self._threads.pop(jid, None)
            self._bus.publish(events.JOB_UPDATED, job_id=jid)
            self._wake.set()

    # ------------------------------------------------------------ control
    def is_active(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._threads

    def pause_job(self, job_id: str) -> bool:
        with self._lock:
            c = self._controls.get(job_id)
        if c:
            c.request_pause()
            return True
        j = self._repo.get_job(job_id)
        if j and j["status"] == JobStatus.WAITING.value:
            self._repo.set_job_status(job_id, JobStatus.PAUSED)
            self._bus.publish(events.JOB_UPDATED, job_id=job_id)
            return True
        return False

    def resume_job(self, job_id: str) -> bool:
        j = self._repo.get_job(job_id)
        if j and j["status"] == JobStatus.PAUSED.value and not self.is_active(job_id):
            self._repo.set_job_status(job_id, JobStatus.WAITING, error_code=None)
            self._bus.publish(events.JOB_UPDATED, job_id=job_id)
            self._wake.set()
            return True
        return False

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            c = self._controls.get(job_id)
        if c:
            c.request_cancel()                     # the worker performs status change + cleanup
            return True
        j = self._repo.get_job(job_id)
        if j and j["status"] in (JobStatus.WAITING.value, JobStatus.PAUSED.value):
            self._repo.set_job_status(job_id, JobStatus.CANCELLED, result="cancelled")
            if self._on_cancel_waiting:
                self._on_cancel_waiting(job_id)
            self._bus.publish(events.JOB_UPDATED, job_id=job_id)
            return True
        return False

    def cancel_all(self) -> int:
        n = 0
        for j in self._repo.queue_snapshot():
            n += 1 if self.cancel_job(j["id"]) else 0
        return n

    def pause_queue(self, reason: str = "user") -> None:
        self.paused, self.pause_reason = True, reason
        with self._lock:
            for c in self._controls.values():
                c.request_pause()
        self._bus.publish(events.QUEUE_STATE, paused=True, reason=reason)

    def resume_queue(self) -> None:
        self.paused, self.pause_reason = False, ""
        for j in self._repo.list_jobs(statuses=[JobStatus.PAUSED.value], limit=10000):
            if not (j.get("awaiting_approval")) and not self.is_active(j["id"]):
                self._repo.set_job_status(j["id"], JobStatus.WAITING)
        self._bus.publish(events.QUEUE_STATE, paused=False, reason="")
        self._wake.set()

    def set_priority(self, job_id: str, priority: int) -> None:
        self._repo.update_job(job_id, priority=priority)
        self._bus.publish(events.JOB_UPDATED, job_id=job_id)

    def move(self, job_id: str, delta: int) -> None:
        """Raise/lower a job relative to its neighbours in the live queue order."""
        snap = [j for j in self._repo.queue_snapshot()]
        ids = [j["id"] for j in snap]
        if job_id not in ids:
            return
        i = ids.index(job_id)
        k = i - 1 if delta > 0 else i + 1
        if not 0 <= k < len(snap):
            return
        a, b = snap[i], snap[k]
        if a["priority"] == b["priority"]:
            self._repo.update_job(job_id, priority=b["priority"] + (1 if delta > 0 else -1))
        else:
            self._repo.update_job(a["id"], priority=b["priority"])
            self._repo.update_job(b["id"], priority=a["priority"])
        self._bus.publish(events.JOB_UPDATED, job_id=job_id)
        self._wake.set()
