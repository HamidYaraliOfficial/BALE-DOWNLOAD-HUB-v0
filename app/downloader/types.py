"""Shared downloader types."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from app.core.exceptions import JobCancelled, JobPaused

ProgressCb = Callable[[int, int | None, float], None]   # done, total (None if unknown), bytes/sec


class JobControl:
    """Cooperative pause/cancel flags checked by every download loop."""

    def __init__(self) -> None:
        self._pause = threading.Event()
        self._cancel = threading.Event()

    def request_pause(self) -> None:
        self._pause.set()

    def request_cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def paused(self) -> bool:
        return self._pause.is_set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled("cancelled by user")
        if self._pause.is_set():
            raise JobPaused("paused by user")

    def wait(self, seconds: float) -> None:
        """Sleep that wakes up early when pause/cancel is requested."""
        end = threading.Event()
        # poll in small slices – simple and dependable across both flags
        import time
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.check()
            end.wait(min(0.2, max(0.0, deadline - time.monotonic())))


@dataclass
class ProbeInfo:
    url: str
    final_url: str = ""
    kind: str = "direct"                  # direct | media
    filename: str = ""
    title: str = ""
    size: int | None = None
    mime: str | None = None
    category: str = "other"
    accept_ranges: bool = False
    etag: str | None = None
    last_modified: str | None = None
    duration: float | None = None
    supported: bool = True
    reason_code: str = ""                 # machine key when supported is False
    reason: str = ""
    resumable: bool = False


@dataclass
class DownloadResult:
    path: str
    size: int
    sha256: str
    filename: str
    kind: str = "direct"
    extra: dict = field(default_factory=dict)
