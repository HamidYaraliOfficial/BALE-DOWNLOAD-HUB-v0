"""Retry policy with exponential back-off, interruptible by pause/cancel."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, TypeVar

import httpx

from app.core.exceptions import DownloadError, FileTooLarge, JobCancelled, JobPaused, SecurityError
from app.downloader.types import JobControl

log = logging.getLogger(__name__)
T = TypeVar("T")


class RetryableHttp(DownloadError):
    """Server answered 429/5xx – worth another attempt."""

    def __init__(self, status: int, retry_after: float | None = None):
        super().__init__(f"HTTP {status}", code=f"http_{status}")
        self.status, self.retry_after = status, retry_after


@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff: float = 2.0
    max_delay: float = 60.0

    def delay(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after:
            return min(retry_after, self.max_delay)
        return min(self.backoff * (2 ** (attempt - 1)), self.max_delay)


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (JobCancelled, JobPaused, FileTooLarge, SecurityError)):
        return False
    return isinstance(exc, (httpx.TransportError, RetryableHttp, ConnectionError, TimeoutError))


def run_with_retries(fn: Callable[[], T], policy: RetryPolicy, ctrl: JobControl | None = None,
                     on_retry: Callable[[int, BaseException], None] | None = None) -> T:
    attempt = 0
    while True:
        try:
            return fn()
        except BaseException as e:  # noqa: BLE001 - we re-raise non-retryables unchanged
            if not is_retryable(e) or attempt >= policy.max_retries:
                raise
            attempt += 1
            delay = policy.delay(attempt, getattr(e, "retry_after", None))
            log.info("retry %s/%s in %.1fs after %s", attempt, policy.max_retries, delay, type(e).__name__)
            if on_retry:
                on_retry(attempt, e)
            if ctrl is not None:
                ctrl.wait(delay)
            else:
                import time
                time.sleep(delay)
