"""SQLAlchemy models. NO file content is ever stored here – only management metadata."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApplicationPreference(Base):
    __tablename__ = "application_preferences"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class BotAccount(Base):
    __tablename__ = "bot_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str] = mapped_column(String(100), default="")
    name: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # NOTE: the token itself lives in the OS credential vault, never here.


class Channel(Base):
    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    username: Mapped[str] = mapped_column(String(100), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    categories: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of categories routed here
    status: Mapped[str] = mapped_column(String(30), default="unverified")
    status_detail: Mapped[str] = mapped_column(Text, default="")
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthorizedUser(Base):
    __tablename__ = "authorized_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="OPERATOR")
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_quota_mb: Mapped[int] = mapped_column(Integer, default=0)  # 0 = use global default
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DownloadJob(Base):
    __tablename__ = "download_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(20), default="desktop")
    requester_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="direct")
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_total: Mapped[int] = mapped_column(BigInteger, default=0)
    size_done: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    destinations: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of channel ids
    caption_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    awaiting_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    cleanup_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    result: Mapped[str | None] = mapped_column(String(60), nullable=True)
    meta: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class QueueEntry(Base):
    __tablename__ = "download_queue"
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("download_jobs.id", ondelete="CASCADE"),
                                        primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PublishHistory(Base):
    __tablename__ = "publish_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("download_jobs.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("channels.id", ondelete="SET NULL"),
                                                   nullable=True)
    channel_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # sent | failed | skipped_duplicate
    method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    filetype: Mapped[str | None] = mapped_column(String(20), nullable=True)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ContentFingerprint(Base):
    """SHA-256 + size only (no name, no URL, no content) – powers duplicate publishing prevention."""
    __tablename__ = "content_fingerprints"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    category: Mapped[str] = mapped_column(String(20), default="system")  # system | security | user
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")


class ErrorLog(Base):
    __tablename__ = "error_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    component: Mapped[str] = mapped_column(String(100), default="")
    level: Mapped[str] = mapped_column(String(20), default="ERROR")
    message: Mapped[str] = mapped_column(Text, default="")


class CaptionTemplate(Base):
    __tablename__ = "caption_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20))  # image|video|audio|document|archive|other|default
    name: Mapped[str] = mapped_column(String(100))
    template: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class CleanupHistory(Base):
    __tablename__ = "cleanup_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    reason: Mapped[str] = mapped_column(String(30), default="published")
    files_removed: Mapped[int] = mapped_column(Integer, default=0)
    bytes_freed: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | partial | failed
    note: Mapped[str] = mapped_column(Text, default="")


Index("ix_publish_history_status", PublishHistory.status)
