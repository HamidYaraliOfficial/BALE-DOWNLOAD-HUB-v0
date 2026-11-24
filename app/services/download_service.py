"""Orchestrates the whole job life-cycle: intake -> validate -> download -> process -> publish -> cleanup."""
from __future__ import annotations

import logging
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256 as _sha
from pathlib import Path

from app.core import events
from app.core.constants import JobStatus
from app.core.exceptions import (DiskSpaceLow, HubError, JobCancelled, JobPaused, NotDownloadable, RateLimited,
                                 SecurityError, UrlBlockedError)
from app.core.logger import mask_text
from app.downloader.queue import QueueManager
from app.downloader.types import JobControl, ProbeInfo
from app.downloader.validators import dedupe_links, extract_links
from app.security.access_control import LOCAL_USER_ID, AccessController, Role
from app.security.url_safety import normalize_url

log = logging.getLogger(__name__)
MB = 1024 * 1024


@dataclass
class AddResult:
    ok: bool
    url: str
    job: dict | None = None
    code: str = ""
    detail: str = ""
    probe: ProbeInfo | None = None


class SpeedTracker:
    """Aggregates live up/down speed for the status bar and the dashboard."""

    def __init__(self) -> None:
        self._d: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()
        self.total_down = 0
        self.total_up = 0

    def set(self, jid: str, phase: str, speed: float) -> None:
        with self._lock:
            self._d[(jid, phase)] = (speed, time.monotonic())

    def clear(self, jid: str) -> None:
        with self._lock:
            for k in [k for k in self._d if k[0] == jid]:
                self._d.pop(k, None)

    def current(self) -> tuple[float, float]:
        now = time.monotonic()
        down = up = 0.0
        with self._lock:
            for (_j, ph), (sp, t) in list(self._d.items()):
                if now - t > 4:
                    continue
                if ph == "download":
                    down += sp
                else:
                    up += sp
        return down, up


class DownloadService:
    def __init__(self, repo, settings_mgr, engine, processor, publishing, cleanup, bus: events.EventBus,
                 access: AccessController):
        self.repo, self.sm, self.engine, self.processor = repo, settings_mgr, engine, processor
        self.publishing, self.cleanup, self.bus, self.access = publishing, cleanup, bus, access
        self.speeds = SpeedTracker()
        self.queue = QueueManager(repo, self._run_job, lambda: self.sm.settings.download.concurrent_downloads,
                                  bus, on_cancel_waiting=lambda jid: self.cleanup.cleanup_job(jid, "cancelled"))

    # ================================================================== lifecycle
    def start(self) -> None:
        self.queue.recover(self.sm.settings.download.auto_resume)
        self.queue.start()

    def shutdown(self) -> None:
        self.queue.shutdown()
        self.engine.close()

    # ================================================================== intake
    def preview(self, url: str) -> ProbeInfo:
        return self.engine.probe(url.strip())

    def add_job(self, url: str, source: str = "desktop", requester_id: int | None = LOCAL_USER_ID,
                destinations: list[int] | None = None, priority: int | None = None,
                scheduled_at: datetime | None = None, caption: str | None = None,
                probe: ProbeInfo | None = None, force: bool = False) -> AddResult:
        url = url.strip()
        s = self.sm.settings
        try:
            key = normalize_url(url)
        except Exception:
            return AddResult(False, url, code="url_invalid")
        url_hash = _sha(key.encode()).hexdigest()
        live = self.repo.find_live_by_hash(url_hash)
        if live:
            return AddResult(False, url, job=live, code="duplicate_active")
        if s.publish.duplicate_detection and not force and self.repo.find_completed_by_hash(url_hash):
            return AddResult(False, url, code="duplicate_done")
        try:
            probe = probe or self.engine.probe(url)
        except UrlBlockedError as e:
            self.repo.add_activity("url_blocked", f"{url[:200]} ({e.code})", requester_id, "security")
            return AddResult(False, url, code=e.code, detail=str(e))
        except HubError as e:
            return AddResult(False, url, code=e.code, detail=mask_text(str(e)))
        except Exception as e:
            log.warning("probe failed: %s", mask_text(str(e)))
            return AddResult(False, url, code="probe_failed", detail=mask_text(str(e))[:200])
        if not probe.supported:
            return AddResult(False, url, code=probe.reason_code, detail=probe.reason, probe=probe)
        try:
            self._check_quota(requester_id, probe.size or 0)
        except RateLimited as e:
            return AddResult(False, url, code=e.code, probe=probe)
        if priority is None:
            priority = 0
            if s.download.priority_small_first and probe.size:
                priority = max(0, 10 - int(probe.size // (10 * MB)))
        if not destinations and not self.repo.default_channel() and not self.repo.list_channels(True):
            return AddResult(False, url, code="no_channel", probe=probe)
        job = self.repo.create_job(
            url=url, url_hash=url_hash, source=source, requester_id=requester_id, kind=probe.kind,
            filename=probe.filename, category=probe.category, mime=probe.mime, size_total=probe.size or 0,
            destinations=destinations or [], priority=priority, scheduled_at=scheduled_at,
            caption_override=caption)
        if s.publish.auto_publish is False:
            self.repo.update_job(job["id"], meta={"hold_for_approval": True})
        self.repo.add_activity("job_added", f"{job['id']} via {source}", requester_id, "user")
        self.bus.publish(events.JOB_ADDED, job_id=job["id"])
        self.queue.wake()
        return AddResult(True, url, job=job, probe=probe)

    def add_links_text(self, text: str, **kw) -> list[AddResult]:
        uniq, dups = dedupe_links(extract_links(text))
        res = [self.add_job(u, **kw) for u in uniq]
        res += [AddResult(False, u, code="duplicate_in_batch") for u in dups]
        return res

    def _check_quota(self, user_id: int | None, size: int) -> None:
        if user_id in (None, LOCAL_USER_ID):
            return
        s = self.sm.settings.security
        u = self.repo.get_user(user_id) or {}
        limit_mb = u.get("daily_quota_mb") or s.user_daily_quota_mb
        if not limit_mb:
            return
        used = self.repo.user_bytes_today(user_id)
        if used + size > limit_mb * MB:
            raise RateLimited("daily quota exceeded", code="quota_exceeded")
        if used + size > 0.9 * limit_mb * MB:
            self.bus.publish(events.QUOTA_NEAR, user_id=user_id, used=used, limit=limit_mb * MB)

    # ================================================================== user controls
    def pause(self, job_id: str) -> bool:
        return self.queue.pause_job(job_id)

    def resume(self, job_id: str) -> bool:
        return self.queue.resume_job(job_id)

    def cancel(self, job_id: str) -> bool:
        return self.queue.cancel_job(job_id)

    def retry(self, job_id: str) -> bool:
        j = self.repo.get_job(job_id)
        if j and j["status"] in (JobStatus.FAILED.value, JobStatus.CANCELLED.value):
            self.repo.set_job_status(job_id, JobStatus.WAITING, error_code=None, error_msg=None, attempts=0,
                                     meta={}, finished_at=None, cleanup_status=None, result=None)
            self.bus.publish(events.JOB_UPDATED, job_id=job_id)
            self.queue.wake()
            return True
        return False

    def approve(self, job_id: str) -> bool:
        j = self.repo.get_job(job_id)
        if j and j.get("awaiting_approval"):
            meta = dict(j["meta"], approved=True)
            self.repo.set_job_status(job_id, JobStatus.WAITING, awaiting_approval=False, meta=meta)
            self.bus.publish(events.JOB_UPDATED, job_id=job_id)
            self.queue.wake()
            return True
        return False

    def job_file(self, job: dict) -> Path | None:
        rel = (job.get("meta") or {}).get("file")
        if not rel:
            return None
        p = self.cleanup.job_dir(job["id"]) / rel
        return p if p.exists() else None

    # ================================================================== pipeline
    def _progress(self, jid: str, phase: str):
        last = [0.0]

        def cb(done, total, speed):
            self.speeds.set(jid, phase, speed or 0.0)
            self.bus.publish(events.JOB_PROGRESS, job_id=jid, done=done, total=total, speed=speed, phase=phase)
            now = time.monotonic()
            if phase == "download" and now - last[0] > 1.0:
                last[0] = now
                self.repo.update_job(jid, size_done=done, **({"size_total": total} if total else {}))
        return cb

    def _set(self, jid: str, status: JobStatus, **kw) -> None:
        self.repo.set_job_status(jid, status, **kw)
        self.bus.publish(events.JOB_UPDATED, job_id=jid, status=status.value)

    def _run_job(self, job: dict, ctrl: JobControl) -> None:
        jid = job["id"]
        s = self.sm.settings
        d = self.cleanup.job_dir(jid)
        meta = dict(job.get("meta") or {})
        try:
            file_path = (d / meta["file"]) if meta.get("file") else None
            stage = meta.get("stage") if file_path and file_path.exists() else None

            if stage is None:
                self._set(jid, JobStatus.VALIDATING)
                free = shutil.disk_usage(self.cleanup.base_dir()).free
                if free < s.download.min_free_disk_mb * MB:
                    raise DiskSpaceLow("free disk space below configured minimum")
                probe = self.engine.probe(job["url"])
                if not probe.supported:
                    raise NotDownloadable(probe.reason or probe.reason_code, code=probe.reason_code)
                self.repo.update_job(jid, filename=probe.filename, size_total=probe.size or 0,
                                     category=probe.category, mime=probe.mime, kind=probe.kind)
                ctrl.check()
                self._set(jid, JobStatus.DOWNLOADING)
                self.bus.publish(events.DOWNLOAD_STARTED, job_id=jid, name=probe.filename)
                res = self.engine.download(job["url"], d, probe, ctrl, self._progress(jid, "download"))
                meta.update(stage="downloaded", file=str(Path(res.path).relative_to(d)))
                self.repo.update_job(jid, size_done=res.size, size_total=res.size, sha256=res.sha256,
                                     filename=res.filename, meta=meta)
                self.speeds.clear(jid)
                self.bus.publish(events.DOWNLOAD_FINISHED, job_id=jid, name=res.filename, size=res.size)
                file_path = Path(res.path)
                job = self.repo.get_job(jid)

            ctrl.check()
            if meta.get("stage") != "ready":
                self._set(jid, JobStatus.PROCESSING)
                pr = self.processor.process(str(file_path), job.get("category") or "other", job.get("url") or "")
                file_path = Path(pr.path)
                meta.update(stage="ready", file=str(file_path.relative_to(d)))
                if pr.notes:
                    meta["notes"] = pr.notes
                meta["media"] = {"duration": pr.info.duration, "resolution": pr.info.resolution}
                self.repo.update_job(jid, category=pr.category, filename=file_path.name,
                                     size_total=pr.info.size, meta=meta)
                job = self.repo.get_job(jid)

            if (meta.get("hold_for_approval") or not s.publish.auto_publish) and not meta.get("approved"):
                self._set(jid, JobStatus.PAUSED, awaiting_approval=True)
                return

            ctrl.check()
            self._set(jid, JobStatus.UPLOADING)
            self.bus.publish(events.UPLOAD_STARTED, job_id=jid, name=file_path.name)

            class _Info:
                duration = (meta.get("media") or {}).get("duration")
                resolution = (meta.get("media") or {}).get("resolution")

            out = self.publishing.publish(job, str(file_path), job.get("category") or "other", job.get("sha256"),
                                          _Info, self._progress(jid, "upload"))
            self.speeds.clear(jid)
            if out.ok:
                self.bus.publish(events.UPLOAD_FINISHED, job_id=jid, name=file_path.name, channels=out.sent_count)
                self._finish(jid, JobStatus.COMPLETED, "published" if out.sent_count else "duplicate_skipped")
            else:
                bad = [r for r in out.results if r.status == "failed"]
                code = bad[0].error_code if bad else "publish_failed"
                msg = "; ".join(f"{r.label}: {r.error}" for r in bad)[:800]
                self._upload_failed(job, code or "publish_failed", msg)

        except JobPaused:
            self.speeds.clear(jid)
            self._set(jid, JobStatus.PAUSED)
        except JobCancelled:
            self.speeds.clear(jid)
            self._finish(jid, JobStatus.CANCELLED, "cancelled", reason="cancelled")
        except DiskSpaceLow:
            self.speeds.clear(jid)
            self._set(jid, JobStatus.WAITING)
            self.bus.publish(events.DISK_LOW, free=0)
            self.queue.pause_queue("disk_low")
        except (SecurityError, NotDownloadable) as e:
            self._fail(jid, e.code, str(e), event=events.DOWNLOAD_ERROR)
        except HubError as e:
            self._maybe_retry_or_fail(job, e.code, str(e))
        except Exception as e:
            log.exception("job %s failed", jid)
            self._maybe_retry_or_fail(job, "internal_error", f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------------ outcomes
    def _finish(self, jid: str, status: JobStatus, result: str, reason: str = "published") -> None:
        self._set(jid, JobStatus.CLEANUP)
        rep = self.cleanup.cleanup_job(jid, reason, scrub=False)
        self.repo.set_job_status(jid, status, result=result, error_code=None if status != JobStatus.FAILED else None)
        if self.sm.settings.cleanup.privacy_mode and rep.status in ("ok", "nothing"):
            self.repo.scrub_job(jid)
        self.bus.publish(events.JOB_FINISHED, job_id=jid, status=status.value)
        self.bus.publish(events.JOB_UPDATED, job_id=jid, status=status.value)

    def _fail(self, jid: str, code: str, msg: str, event: str = events.DOWNLOAD_ERROR) -> None:
        self.speeds.clear(jid)
        msg = mask_text(msg)[:800]
        self.repo.add_error("job", "ERROR", f"{jid}: {code}: {msg}")
        self.repo.set_job_status(jid, JobStatus.CLEANUP, error_code=code, error_msg=msg)
        self.bus.publish(event, job_id=jid, code=code, detail=msg)
        self.cleanup.cleanup_job(jid, "failed", scrub=False)        # partial/incomplete data is removed
        self.repo.set_job_status(jid, JobStatus.FAILED, result="failed", error_code=code, error_msg=msg)
        if self.sm.settings.cleanup.privacy_mode:
            self.repo.scrub_job(jid)
        self.bus.publish(events.JOB_FINISHED, job_id=jid, status="failed")
        self.bus.publish(events.JOB_UPDATED, job_id=jid, status="failed")

    def _upload_failed(self, job: dict, code: str, msg: str) -> None:
        jid, s = job["id"], self.sm.settings
        if s.download.auto_retry and job["attempts"] <= s.download.retry_count and code not in (
                "no_channel", "too_large_for_bale", "bale_auth_error"):
            delay = s.download.retry_backoff_s * (2 ** max(0, job["attempts"] - 1))
            self.repo.set_job_status(jid, JobStatus.WAITING, error_code=code, error_msg=mask_text(msg)[:500],
                                     scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=delay))
            return
        self._fail(jid, code, msg, event=events.UPLOAD_ERROR)

    def _maybe_retry_or_fail(self, job: dict, code: str, msg: str) -> None:
        jid, s = job["id"], self.sm.settings
        transient = code in ("bale_network_error", "download_failed", "http_429", "http_500", "http_502",
                             "http_503", "http_504", "internal_error")
        ev = events.UPLOAD_ERROR if code.startswith("bale") or code.startswith("publish") else events.DOWNLOAD_ERROR
        if transient and s.download.auto_retry and job["attempts"] <= s.download.retry_count:
            delay = s.download.retry_backoff_s * (2 ** max(0, job["attempts"] - 1))
            self.speeds.clear(jid)
            self.repo.set_job_status(jid, JobStatus.WAITING, error_code=code, error_msg=mask_text(msg)[:500],
                                     scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=delay))
            return
        self._fail(jid, code, msg, event=ev)
