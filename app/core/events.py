"""Tiny thread-safe publish/subscribe bus. The UI bridges it to Qt signals."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)

JOB_ADDED = "job.added"
JOB_UPDATED = "job.updated"
JOB_PROGRESS = "job.progress"
JOB_FINISHED = "job.finished"
DOWNLOAD_STARTED = "notify.download_started"
DOWNLOAD_FINISHED = "notify.download_finished"
UPLOAD_STARTED = "notify.upload_started"
UPLOAD_FINISHED = "notify.upload_finished"
CONNECTION_ERROR = "notify.connection_error"
DOWNLOAD_ERROR = "notify.download_error"
UPLOAD_ERROR = "notify.upload_error"
DISK_LOW = "notify.disk_low"
QUOTA_NEAR = "notify.quota_near"
BOT_DISCONNECTED = "notify.bot_disconnected"
CLEANUP_DONE = "notify.cleanup_done"
BOT_STATUS = "bot.status"
SETTINGS_CHANGED = "settings.changed"
QUEUE_STATE = "queue.state"
DATA_CHANGED = "data.changed"

NOTIFICATION_EVENTS = [
    DOWNLOAD_STARTED, DOWNLOAD_FINISHED, UPLOAD_STARTED, UPLOAD_FINISHED,
    CONNECTION_ERROR, DOWNLOAD_ERROR, UPLOAD_ERROR, DISK_LOW, QUOTA_NEAR,
    BOT_DISCONNECTED, CLEANUP_DONE,
]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[..., None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event: str, fn: Callable[..., None]) -> None:
        with self._lock:
            self._subs[event].append(fn)

    def unsubscribe(self, event: str, fn: Callable[..., None]) -> None:
        with self._lock:
            if fn in self._subs.get(event, []):
                self._subs[event].remove(fn)

    def publish(self, event: str, /, **payload: Any) -> None:
        with self._lock:
            targets = list(self._subs.get(event, [])) + list(self._subs.get("*", []))
        for fn in targets:
            try:
                fn(event, **payload)
            except Exception:  # a broken listener must never break the pipeline
                log.exception("event listener failed for %s", event)
