"""Data access layer. Returns plain dicts so no ORM object crosses thread boundaries."""
from __future__ import annotations

import gzip
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update

from app.core.constants import (ACTIVE_STATUSES, LIVE_STATUSES, TERMINAL_STATUSES, JobStatus)
from app.core.logger import mask_text
from app.database import models as m
from app.database.manager import DatabaseManager
from app.database.models import utcnow

_JSON_FIELDS = {"destinations": list, "meta": dict, "categories": list}


def _row(obj) -> dict[str, Any]:
    d = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    for k, typ in _JSON_FIELDS.items():
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                d[k] = typ()
    return d


def _enc(fields: dict[str, Any]) -> dict[str, Any]:
    out = dict(fields)
    for k in _JSON_FIELDS:
        if k in out and not isinstance(out[k], str):
            out[k] = json.dumps(out[k])
    return out


class Repository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # ------------------------------------------------------------------ settings / prefs
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.db.session_scope() as s:
            r = s.get(m.Setting, key)
            return r.value if r else default

    def set_setting(self, key: str, value: str) -> None:
        with self.db.session_scope() as s:
            r = s.get(m.Setting, key)
            if r:
                r.value, r.updated_at = value, utcnow()
            else:
                s.add(m.Setting(key=key, value=value))

    def all_settings(self) -> dict[str, str]:
        with self.db.session_scope() as s:
            return {r.key: r.value for r in s.scalars(select(m.Setting))}

    def get_pref(self, key: str, default: str | None = None) -> str | None:
        with self.db.session_scope() as s:
            r = s.get(m.ApplicationPreference, key)
            return r.value if r else default

    def set_pref(self, key: str, value: str) -> None:
        with self.db.session_scope() as s:
            r = s.get(m.ApplicationPreference, key)
            if r:
                r.value = value
            else:
                s.add(m.ApplicationPreference(key=key, value=value))

    # ------------------------------------------------------------------ bot account
    def set_bot_account(self, bot_id: int | None, username: str, name: str) -> None:
        with self.db.session_scope() as s:
            for r in s.scalars(select(m.BotAccount)):
                r.active = False
            s.add(m.BotAccount(bot_id=bot_id, username=username, name=name, active=True))

    def get_bot_account(self) -> dict | None:
        with self.db.session_scope() as s:
            r = s.scalars(select(m.BotAccount).where(m.BotAccount.active.is_(True))
                          .order_by(m.BotAccount.id.desc())).first()
            return _row(r) if r else None

    def clear_bot_account(self) -> None:
        with self.db.session_scope() as s:
            s.execute(delete(m.BotAccount))

    # ------------------------------------------------------------------ channels
    def add_channel(self, chat_id: str, title: str = "", username: str = "", make_default: bool = False,
                    categories: list[str] | None = None) -> dict:
        with self.db.session_scope() as s:
            if s.scalars(select(m.Channel).where(m.Channel.chat_id == chat_id)).first():
                raise ValueError("channel already exists")
            first = s.scalar(select(func.count(m.Channel.id))) == 0
            ch = m.Channel(chat_id=chat_id, title=title, username=username,
                           is_default=bool(make_default or first), categories=json.dumps(categories or []))
            s.add(ch)
            s.flush()
            if ch.is_default:
                s.execute(update(m.Channel).where(m.Channel.id != ch.id).values(is_default=False))
            return _row(ch)

    def update_channel(self, channel_id: int, **fields) -> dict | None:
        fields = _enc(fields)
        with self.db.session_scope() as s:
            ch = s.get(m.Channel, channel_id)
            if not ch:
                return None
            for k, v in fields.items():
                setattr(ch, k, v)
            if fields.get("is_default"):
                s.execute(update(m.Channel).where(m.Channel.id != channel_id).values(is_default=False))
            return _row(ch)

    def delete_channel(self, channel_id: int) -> None:
        with self.db.session_scope() as s:
            ch = s.get(m.Channel, channel_id)
            if not ch:
                return
            was_default = ch.is_default
            s.delete(ch)
            s.flush()
            if was_default:
                nxt = s.scalars(select(m.Channel).order_by(m.Channel.id)).first()
                if nxt:
                    nxt.is_default = True

    def get_channel(self, channel_id: int) -> dict | None:
        with self.db.session_scope() as s:
            ch = s.get(m.Channel, channel_id)
            return _row(ch) if ch else None

    def list_channels(self, enabled_only: bool = False) -> list[dict]:
        with self.db.session_scope() as s:
            q = select(m.Channel).order_by(m.Channel.id)
            if enabled_only:
                q = q.where(m.Channel.enabled.is_(True))
            return [_row(c) for c in s.scalars(q)]

    def default_channel(self) -> dict | None:
        with self.db.session_scope() as s:
            ch = s.scalars(select(m.Channel).where(m.Channel.is_default.is_(True),
                                                   m.Channel.enabled.is_(True))).first()
            return _row(ch) if ch else None

    # ------------------------------------------------------------------ users
    def add_user(self, user_id: int, name: str = "", role: str = "OPERATOR", quota_mb: int = 0) -> dict:
        with self.db.session_scope() as s:
            u = s.scalars(select(m.AuthorizedUser).where(m.AuthorizedUser.user_id == user_id)).first()
            if u:
                u.display_name, u.role, u.blocked = name or u.display_name, role, False
            else:
                u = m.AuthorizedUser(user_id=user_id, display_name=name, role=role, daily_quota_mb=quota_mb)
                s.add(u)
            s.flush()
            return _row(u)

    def get_user(self, user_id: int) -> dict | None:
        with self.db.session_scope() as s:
            u = s.scalars(select(m.AuthorizedUser).where(m.AuthorizedUser.user_id == user_id)).first()
            return _row(u) if u else None

    def list_users(self) -> list[dict]:
        with self.db.session_scope() as s:
            return [_row(u) for u in s.scalars(select(m.AuthorizedUser).order_by(m.AuthorizedUser.id))]

    def update_user(self, user_id: int, **fields) -> dict | None:
        with self.db.session_scope() as s:
            u = s.scalars(select(m.AuthorizedUser).where(m.AuthorizedUser.user_id == user_id)).first()
            if not u:
                return None
            for k, v in fields.items():
                setattr(u, k, v)
            return _row(u)

    def remove_user(self, user_id: int) -> bool:
        with self.db.session_scope() as s:
            r = s.execute(delete(m.AuthorizedUser).where(m.AuthorizedUser.user_id == user_id))
            return r.rowcount > 0

    def user_bytes_today(self, user_id: int) -> int:
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        with self.db.session_scope() as s:
            v = s.scalar(select(func.coalesce(func.sum(m.DownloadJob.size_total), 0)).where(
                m.DownloadJob.requester_id == user_id, m.DownloadJob.created_at >= start,
                m.DownloadJob.status != JobStatus.CANCELLED.value))
            return int(v or 0)

    # ------------------------------------------------------------------ jobs
    def create_job(self, *, url: str | None, url_hash: str | None, source: str = "desktop",
                   requester_id: int | None = None, kind: str = "direct", filename: str | None = None,
                   category: str | None = None, mime: str | None = None, size_total: int = 0,
                   destinations: list[int] | None = None, priority: int = 0,
                   scheduled_at: datetime | None = None, caption_override: str | None = None,
                   meta: dict | None = None, awaiting_approval_after_download: bool = False) -> dict:
        jid = str(uuid.uuid4())
        with self.db.session_scope() as s:
            job = m.DownloadJob(id=jid, url=url, url_hash=url_hash, source=source, requester_id=requester_id,
                                kind=kind, filename=filename, category=category, mime=mime,
                                size_total=size_total or 0, destinations=json.dumps(destinations or []),
                                caption_override=caption_override, meta=json.dumps(meta or {}),
                                status=JobStatus.WAITING.value)
            s.add(job)
            s.flush()
            s.add(m.QueueEntry(job_id=jid, priority=priority, scheduled_at=scheduled_at))
            return self._job_dict(s, job)

    def _job_dict(self, s, job) -> dict:
        d = _row(job)
        q = s.get(m.QueueEntry, job.id)
        d["priority"] = q.priority if q else 0
        d["scheduled_at"] = q.scheduled_at if q else None
        return d

    def get_job(self, job_id: str) -> dict | None:
        with self.db.session_scope() as s:
            j = s.get(m.DownloadJob, job_id)
            return self._job_dict(s, j) if j else None

    def update_job(self, job_id: str, **fields) -> dict | None:
        prio = fields.pop("priority", None)
        sched = fields.pop("scheduled_at", "__keep__")
        fields = _enc(fields)
        with self.db.session_scope() as s:
            j = s.get(m.DownloadJob, job_id)
            if not j:
                return None
            for k, v in fields.items():
                setattr(j, k, v)
            q = s.get(m.QueueEntry, job_id)
            if q is not None:
                if prio is not None:
                    q.priority = prio
                if sched != "__keep__":
                    q.scheduled_at = sched
            return self._job_dict(s, j)

    def set_job_status(self, job_id: str, status: JobStatus | str, **fields) -> dict | None:
        status = status.value if isinstance(status, JobStatus) else status
        now = utcnow()
        if status in (JobStatus.DOWNLOADING.value, JobStatus.VALIDATING.value) and "started_at" not in fields:
            fields.setdefault("started_at", now)
        if status in TERMINAL_STATUSES:
            fields.setdefault("finished_at", now)
        return self.update_job(job_id, status=status, **fields)

    def delete_job(self, job_id: str) -> None:
        with self.db.session_scope() as s:
            s.execute(delete(m.DownloadJob).where(m.DownloadJob.id == job_id))

    def remove_from_queue(self, job_id: str) -> None:
        with self.db.session_scope() as s:
            s.execute(delete(m.QueueEntry).where(m.QueueEntry.job_id == job_id))

    def list_jobs(self, statuses: list[str] | tuple[str, ...] | None = None, search: str | None = None,
                  since: datetime | None = None, until: datetime | None = None, channel_id: int | None = None,
                  limit: int = 500, offset: int = 0, newest_first: bool = True) -> list[dict]:
        with self.db.session_scope() as s:
            q = select(m.DownloadJob)
            if statuses:
                q = q.where(m.DownloadJob.status.in_(list(statuses)))
            if search:
                like = f"%{search}%"
                q = q.where(or_(m.DownloadJob.filename.ilike(like), m.DownloadJob.url.ilike(like),
                                m.DownloadJob.id.ilike(like)))
            if since:
                q = q.where(m.DownloadJob.created_at >= since)
            if until:
                q = q.where(m.DownloadJob.created_at <= until)
            if channel_id is not None:
                q = q.where(m.DownloadJob.id.in_(select(m.PublishHistory.job_id).where(
                    m.PublishHistory.channel_id == channel_id)))
            q = q.order_by(m.DownloadJob.created_at.desc() if newest_first else m.DownloadJob.created_at.asc())
            q = q.limit(limit).offset(offset)
            return [self._job_dict(s, j) for j in s.scalars(q)]

    def queue_snapshot(self) -> list[dict]:
        """Live jobs ordered the way the dispatcher will run them."""
        with self.db.session_scope() as s:
            q = (select(m.DownloadJob, m.QueueEntry)
                 .join(m.QueueEntry, m.QueueEntry.job_id == m.DownloadJob.id)
                 .where(m.DownloadJob.status.in_(LIVE_STATUSES))
                 .order_by(m.QueueEntry.priority.desc(), m.DownloadJob.created_at.asc()))
            out = []
            for j, qe in s.execute(q).all():
                d = _row(j)
                d["priority"], d["scheduled_at"] = qe.priority, qe.scheduled_at
                out.append(d)
            return out

    def next_runnable(self, now: datetime, exclude_hashes: set[str], limit: int = 1) -> list[dict]:
        with self.db.session_scope() as s:
            q = (select(m.DownloadJob, m.QueueEntry)
                 .join(m.QueueEntry, m.QueueEntry.job_id == m.DownloadJob.id)
                 .where(m.DownloadJob.status == JobStatus.WAITING.value,
                        or_(m.QueueEntry.scheduled_at.is_(None), m.QueueEntry.scheduled_at <= now))
                 .order_by(m.QueueEntry.priority.desc(), m.DownloadJob.created_at.asc()))
            out: list[dict] = []
            for j, qe in s.execute(q).all():
                if j.url_hash and j.url_hash in exclude_hashes:
                    continue
                d = _row(j)
                d["priority"], d["scheduled_at"] = qe.priority, qe.scheduled_at
                out.append(d)
                if len(out) >= limit:
                    break
            return out

    def find_live_by_hash(self, url_hash: str) -> dict | None:
        with self.db.session_scope() as s:
            j = s.scalars(select(m.DownloadJob).where(m.DownloadJob.url_hash == url_hash,
                                                      m.DownloadJob.status.in_(LIVE_STATUSES))).first()
            return _row(j) if j else None

    def find_completed_by_hash(self, url_hash: str) -> dict | None:
        with self.db.session_scope() as s:
            j = s.scalars(select(m.DownloadJob).where(m.DownloadJob.url_hash == url_hash,
                                                      m.DownloadJob.status == JobStatus.COMPLETED.value)
                          .order_by(m.DownloadJob.finished_at.desc())).first()
            return _row(j) if j else None

    def jobs_in_statuses(self, statuses: tuple[str, ...]) -> list[dict]:
        return self.list_jobs(statuses=list(statuses), limit=10000)

    def count_by_status(self) -> dict[str, int]:
        with self.db.session_scope() as s:
            rows = s.execute(select(m.DownloadJob.status, func.count()).group_by(m.DownloadJob.status)).all()
            return {k: v for k, v in rows}

    def all_job_ids(self) -> set[str]:
        with self.db.session_scope() as s:
            return set(s.scalars(select(m.DownloadJob.id)))

    def live_job_ids(self) -> set[str]:
        with self.db.session_scope() as s:
            return set(s.scalars(select(m.DownloadJob.id).where(m.DownloadJob.status.in_(LIVE_STATUSES))))

    def scrub_job(self, job_id: str) -> None:
        """Privacy mode: drop URL, file name and free-text details of a finished job."""
        with self.db.session_scope() as s:
            j = s.get(m.DownloadJob, job_id)
            if not j:
                return
            j.url = j.url_hash = j.filename = j.caption_override = None
            j.meta = "{}"
            if j.error_msg:
                j.error_msg = None
            j.sha256 = None
            s.execute(update(m.PublishHistory).where(m.PublishHistory.job_id == job_id)
                      .values(filename=None, error=None))

    # ------------------------------------------------------------------ publish history / fingerprints
    def add_publish(self, job_id: str, channel_id: int | None, channel_label: str, status: str,
                    method: str | None = None, message_id: int | None = None, error: str | None = None,
                    size: int = 0, filetype: str | None = None, filename: str | None = None) -> None:
        with self.db.session_scope() as s:
            s.add(m.PublishHistory(job_id=job_id, channel_id=channel_id, channel_label=channel_label,
                                   status=status, method=method, message_id=message_id,
                                   error=mask_text(error)[:1000] if error else None, size=size,
                                   filetype=filetype, filename=filename))

    def list_publishes(self, job_id: str | None = None, status: str | None = None, search: str | None = None,
                       since: datetime | None = None, until: datetime | None = None,
                       channel_id: int | None = None, limit: int = 500) -> list[dict]:
        with self.db.session_scope() as s:
            q = select(m.PublishHistory)
            if job_id:
                q = q.where(m.PublishHistory.job_id == job_id)
            if status:
                q = q.where(m.PublishHistory.status == status)
            if search:
                q = q.where(m.PublishHistory.filename.ilike(f"%{search}%"))
            if since:
                q = q.where(m.PublishHistory.sent_at >= since)
            if until:
                q = q.where(m.PublishHistory.sent_at <= until)
            if channel_id is not None:
                q = q.where(m.PublishHistory.channel_id == channel_id)
            q = q.order_by(m.PublishHistory.sent_at.desc()).limit(limit)
            return [_row(r) for r in s.scalars(q)]

    def has_fingerprint(self, sha256: str, channel_id: int) -> bool:
        with self.db.session_scope() as s:
            return s.get(m.ContentFingerprint, (sha256, channel_id)) is not None

    def add_fingerprint(self, sha256: str, channel_id: int, size: int) -> None:
        with self.db.session_scope() as s:
            if s.get(m.ContentFingerprint, (sha256, channel_id)) is None:
                s.add(m.ContentFingerprint(sha256=sha256, channel_id=channel_id, size=size))

    def clear_fingerprints(self) -> int:
        with self.db.session_scope() as s:
            return s.execute(delete(m.ContentFingerprint)).rowcount

    # ------------------------------------------------------------------ logs
    def add_activity(self, action: str, detail: str = "", actor_id: int | None = None,
                     category: str = "system") -> None:
        with self.db.session_scope() as s:
            s.add(m.ActivityLog(actor_id=actor_id, category=category, action=action,
                                detail=mask_text(detail)[:2000]))

    def list_activity(self, category: str | None = None, actor_id: int | None = None, search: str | None = None,
                      since: datetime | None = None, until: datetime | None = None, limit: int = 500) -> list[dict]:
        with self.db.session_scope() as s:
            q = select(m.ActivityLog)
            if category:
                q = q.where(m.ActivityLog.category == category)
            if actor_id is not None:
                q = q.where(m.ActivityLog.actor_id == actor_id)
            if search:
                q = q.where(or_(m.ActivityLog.detail.ilike(f"%{search}%"), m.ActivityLog.action.ilike(f"%{search}%")))
            if since:
                q = q.where(m.ActivityLog.ts >= since)
            if until:
                q = q.where(m.ActivityLog.ts <= until)
            return [_row(r) for r in s.scalars(q.order_by(m.ActivityLog.ts.desc(), m.ActivityLog.id.desc()).limit(limit))]

    def add_error(self, component: str, level: str, message: str) -> None:
        with self.db.session_scope() as s:
            s.add(m.ErrorLog(component=component[:100], level=level, message=mask_text(message)[:4000]))

    def list_errors(self, search: str | None = None, since: datetime | None = None, until: datetime | None = None,
                    limit: int = 500) -> list[dict]:
        with self.db.session_scope() as s:
            q = select(m.ErrorLog)
            if search:
                q = q.where(or_(m.ErrorLog.message.ilike(f"%{search}%"), m.ErrorLog.component.ilike(f"%{search}%")))
            if since:
                q = q.where(m.ErrorLog.ts >= since)
            if until:
                q = q.where(m.ErrorLog.ts <= until)
            return [_row(r) for r in s.scalars(q.order_by(m.ErrorLog.ts.desc(), m.ErrorLog.id.desc()).limit(limit))]

    # ------------------------------------------------------------------ caption templates
    def list_templates(self) -> list[dict]:
        with self.db.session_scope() as s:
            return [_row(t) for t in s.scalars(select(m.CaptionTemplate).order_by(m.CaptionTemplate.id))]

    def get_template_for(self, kind: str) -> dict | None:
        with self.db.session_scope() as s:
            for k in (kind, "default"):
                t = s.scalars(select(m.CaptionTemplate).where(m.CaptionTemplate.kind == k)
                              .order_by(m.CaptionTemplate.is_default.desc(), m.CaptionTemplate.id)).first()
                if t:
                    return _row(t)
            return None

    def save_template(self, kind: str, name: str, template: str, is_default: bool = True,
                      template_id: int | None = None) -> dict:
        with self.db.session_scope() as s:
            if template_id:
                t = s.get(m.CaptionTemplate, template_id)
                if not t:
                    raise ValueError("template not found")
                t.kind, t.name, t.template, t.is_default = kind, name, template, is_default
            else:
                t = m.CaptionTemplate(kind=kind, name=name, template=template, is_default=is_default)
                s.add(t)
            s.flush()
            if is_default:
                s.execute(update(m.CaptionTemplate).where(m.CaptionTemplate.kind == kind,
                                                          m.CaptionTemplate.id != t.id).values(is_default=False))
            return _row(t)

    def delete_template(self, template_id: int) -> None:
        with self.db.session_scope() as s:
            s.execute(delete(m.CaptionTemplate).where(m.CaptionTemplate.id == template_id))

    # ------------------------------------------------------------------ cleanup history
    def add_cleanup(self, job_id: str | None, reason: str, files_removed: int, bytes_freed: int,
                    status: str = "ok", note: str = "") -> None:
        with self.db.session_scope() as s:
            s.add(m.CleanupHistory(job_id=job_id, reason=reason, files_removed=files_removed,
                                   bytes_freed=bytes_freed, status=status, note=note[:500]))

    def list_cleanups(self, since: datetime | None = None, limit: int = 500) -> list[dict]:
        with self.db.session_scope() as s:
            q = select(m.CleanupHistory)
            if since:
                q = q.where(m.CleanupHistory.ts >= since)
            return [_row(r) for r in s.scalars(q.order_by(m.CleanupHistory.ts.desc(), m.CleanupHistory.id.desc())
                                                .limit(limit))]

    def total_bytes_freed(self) -> int:
        with self.db.session_scope() as s:
            return int(s.scalar(select(func.coalesce(func.sum(m.CleanupHistory.bytes_freed), 0))) or 0)

    def mark_cleanup(self, job_id: str, status: str) -> None:
        self.update_job(job_id, cleanup_status=status)

    def jobs_needing_cleanup_retry(self) -> list[dict]:
        with self.db.session_scope() as s:
            q = select(m.DownloadJob).where(m.DownloadJob.cleanup_status == "failed")
            return [_row(j) for j in s.scalars(q)]

    # ------------------------------------------------------------------ stats for dashboard
    def stats(self) -> dict[str, Any]:
        today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        with self.db.session_scope() as s:
            by_status = {k: v for k, v in s.execute(
                select(m.DownloadJob.status, func.count()).group_by(m.DownloadJob.status)).all()}
            total = sum(by_status.values())
            sent_today = s.scalar(select(func.coalesce(func.sum(m.PublishHistory.size), 0)).where(
                m.PublishHistory.status == "sent", m.PublishHistory.sent_at >= today)) or 0
            recv_today = s.scalar(select(func.coalesce(func.sum(m.DownloadJob.size_done), 0)).where(
                m.DownloadJob.created_at >= today)) or 0
            published = s.scalar(select(func.count()).select_from(m.PublishHistory)
                                 .where(m.PublishHistory.status == "sent")) or 0
            errors = s.scalar(select(func.count()).select_from(m.ErrorLog)) or 0
            return {
                "total": total, "by_status": by_status,
                "completed": by_status.get("completed", 0), "failed": by_status.get("failed", 0),
                "queued": by_status.get("waiting", 0) + by_status.get("paused", 0),
                "active": sum(by_status.get(k, 0) for k in ACTIVE_STATUSES),
                "published": int(published), "errors_logged": int(errors),
                "bytes_received_today": int(recv_today), "bytes_sent_today": int(sent_today),
            }

    def daily_series(self, days: int = 14) -> dict[str, list]:
        start = (utcnow() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        labels = [(start + timedelta(days=i)).date() for i in range(days)]
        dl = {d: 0 for d in labels}
        pub = {d: 0 for d in labels}
        ok = {d: 0 for d in labels}
        bad = {d: 0 for d in labels}
        recv = {d: 0 for d in labels}
        sent = {d: 0 for d in labels}
        with self.db.session_scope() as s:
            for j in s.scalars(select(m.DownloadJob).where(m.DownloadJob.created_at >= start)):
                d = j.created_at.date()
                if d in dl:
                    dl[d] += 1
                    recv[d] += int(j.size_done or 0)
                    if j.status == "completed":
                        ok[d] += 1
                    elif j.status == "failed":
                        bad[d] += 1
            for p in s.scalars(select(m.PublishHistory).where(m.PublishHistory.sent_at >= start,
                                                             m.PublishHistory.status == "sent")):
                d = p.sent_at.date()
                if d in pub:
                    pub[d] += 1
                    sent[d] += int(p.size or 0)
        return {"labels": [d.strftime("%m-%d") for d in labels], "downloads": [dl[d] for d in labels],
                "published": [pub[d] for d in labels], "ok": [ok[d] for d in labels],
                "failed": [bad[d] for d in labels], "bytes_received": [recv[d] for d in labels],
                "bytes_sent": [sent[d] for d in labels]}

    def type_distribution(self) -> dict[str, int]:
        with self.db.session_scope() as s:
            rows = s.execute(select(m.DownloadJob.category, func.count()).where(
                m.DownloadJob.status == "completed").group_by(m.DownloadJob.category)).all()
            return {(k or "other"): v for k, v in rows}

    def size_distribution(self) -> dict[str, int]:
        buckets = {"<1MB": 0, "1-10MB": 0, "10-50MB": 0, ">50MB": 0}
        with self.db.session_scope() as s:
            for (sz,) in s.execute(select(m.DownloadJob.size_total).where(m.DownloadJob.status == "completed")):
                mb = (sz or 0) / 1048576
                key = "<1MB" if mb < 1 else "1-10MB" if mb < 10 else "10-50MB" if mb < 50 else ">50MB"
                buckets[key] += 1
        return buckets

    # ------------------------------------------------------------------ retention
    def purge_old(self, retention_days: int, archive_dir: Path | None = None) -> dict[str, int]:
        cutoff = utcnow() - timedelta(days=retention_days)
        counts = {"jobs": 0, "activity": 0, "errors": 0, "cleanups": 0}
        with self.db.session_scope() as s:
            if archive_dir is not None:
                archive_dir.mkdir(parents=True, exist_ok=True)
                path = archive_dir / f"archive_{utcnow():%Y%m%d_%H%M%S}.jsonl.gz"
                rows: list[dict] = []
                for model, tag in ((m.ActivityLog, "activity"), (m.ErrorLog, "error"),
                                   (m.CleanupHistory, "cleanup")):
                    for r in s.scalars(select(model).where(model.ts < cutoff)):
                        rows.append({"type": tag, **{c.name: str(getattr(r, c.name)) for c in r.__table__.columns}})
                for j in s.scalars(select(m.DownloadJob).where(m.DownloadJob.created_at < cutoff,
                                                               m.DownloadJob.status.in_(TERMINAL_STATUSES))):
                    rows.append({"type": "job", **{c.name: str(getattr(j, c.name)) for c in j.__table__.columns
                                                   if c.name not in ("url", "filename", "meta")}})
                if rows:
                    with gzip.open(path, "wt", encoding="utf-8") as f:
                        for r in rows:
                            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            counts["activity"] = s.execute(delete(m.ActivityLog).where(m.ActivityLog.ts < cutoff)).rowcount
            counts["errors"] = s.execute(delete(m.ErrorLog).where(m.ErrorLog.ts < cutoff)).rowcount
            counts["cleanups"] = s.execute(delete(m.CleanupHistory).where(m.CleanupHistory.ts < cutoff)).rowcount
            counts["jobs"] = s.execute(delete(m.DownloadJob).where(
                m.DownloadJob.created_at < cutoff, m.DownloadJob.status.in_(TERMINAL_STATUSES))).rowcount
            s.execute(delete(m.ContentFingerprint).where(m.ContentFingerprint.first_seen < cutoff))
        return counts

    def wipe_logs(self) -> None:
        with self.db.session_scope() as s:
            for model in (m.ActivityLog, m.ErrorLog):
                s.execute(delete(model))
